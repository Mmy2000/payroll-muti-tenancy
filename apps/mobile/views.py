"""The mobile app's endpoints (`/api/v1/`, docs/mobile-api.md), answering as PayRole's did.

Every view runs in English, as PayRole's API did (DRF's and SimpleJWT's own messages are
English there); the business messages are the contract's Arabic ones. Errors are DRF's own
shape, not the web API's envelope.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone, translation
from django.utils.crypto import get_random_string
from rest_framework import exceptions, permissions, status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.employees.models import Employee
from apps.iam import throttle
from apps.iam.authz import build_actor
from apps.iam.catalog import WILDCARD
from apps.iam.signals import client_ip
from apps.notifications import services as notifications

from . import contract, devices, qr, services
from . import serializers as s
from .auth import DEVICE_CLAIM, AppTokenAuthentication, active_membership, tokens_for
from .contract import AppError
from .models import DeviceMethod, TrackSession

SIGNIN, MONITOR = "mobile.signin", "mobile.monitor.track"


def app_errors(exc, context):
    if isinstance(exc, AppError):
        return Response({"detail": exc.detail, "code": exc.code, **exc.extra},
                        status=exc.status)
    return exception_handler(exc, context)  # DRF's own shapes and messages


class EnglishMixin:
    renderer_classes = [JSONRenderer]

    def get_exception_handler(self):
        return app_errors

    def dispatch(self, request, *args, **kwargs):
        with translation.override("en"):
            return super().dispatch(request, *args, **kwargs)


class CanUseApp(permissions.BasePermission):
    def has_permission(self, request, view):
        actor = getattr(request._request, "actor", None)
        return bool(request.user and request.user.is_authenticated and actor is not None
                    and actor.can(SIGNIN))


class CanMonitor(CanUseApp):
    message = contract.MONITOR_ONLY

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request._request.actor.can(MONITOR)


class AppView(EnglishMixin, APIView):
    authentication_classes = [AppTokenAuthentication]
    permission_classes = [CanUseApp]

    @property
    def member(self):
        return self.request._request.membership

    def employee(self, *, status_code: int = 404) -> Employee:
        return services.employee_of(self.member, status=status_code)


def _valid(serializer_class, data, **extra):
    payload = serializer_class(data=data, **extra)
    payload.is_valid(raise_exception=True)
    return payload.validated_data


def _role(actor) -> str | None:
    if WILDCARD in actor.grants:
        return "owner"
    codes = set(actor.grants) - {SIGNIN}
    if not codes:
        return "employee"
    return "staff"


def _employee_or_none(member):
    try:
        return services.employee_of(member)
    except AppError:
        return None


# --- signing in ------------------------------------------------------------------------------


def _signed_in(member, device, request) -> dict:
    """The answer to a sign-in, by password or by QR."""
    user, actor = member.user, build_actor(member)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return {**tokens_for(member, device.pk if device else None), "username": member.username,
            "role": _role(actor), "is_superuser": actor.can(MONITOR),
            "employee": s.employee(_employee_or_none(member), request)}


class LoginView(EnglishMixin, APIView):
    authentication_classes = ()
    permission_classes = ()

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'  # a wrong password is 401, as SimpleJWT's own views say

    def post(self, request):
        data = _valid(s.LoginSerializer, request.data)
        username = data["username"].strip()
        user = authenticate(request._request, username=username, password=data["password"])
        member = active_membership(user) if user is not None else None
        actor = build_actor(member) if member is not None else None
        if member is None or not actor.can(SIGNIN):
            raise exceptions.AuthenticationFailed(  # DRF's own: no "code", as PayRole
                "No active account found with the given credentials")
        throttle.succeeded(request._request, username)
        device = devices.sign_in(member, data["device_id"], DeviceMethod.PASSWORD)
        return Response(_signed_in(member, device, request))


class QrLoginView(EnglishMixin, APIView):
    """The app's scan: a one-time code for the same answer as a login (apps/mobile/qr.py)."""

    authentication_classes = ()
    permission_classes = ()

    def post(self, request):
        data = _valid(s.QrLoginSerializer, request.data)
        tries = f"qr:{client_ip(request._request)}"
        if throttle.locked_for(request._request, tries):
            raise AppError("qr_locked", status=429)
        try:
            member, device = qr.redeem(data["code"], data["device_id"])
        except AppError as error:
            if error.code == "qr_invalid":  # guessing; an old QR scanned by mistake isn't
                throttle.failed(request._request, tries)
            raise
        return Response(_signed_in(member, device, request))


class RefreshView(EnglishMixin, TokenRefreshView):
    serializer_class = s.TenantRefreshSerializer


class VerifyView(EnglishMixin, TokenVerifyView):
    pass


class ChangePasswordView(AppView):
    def post(self, request):
        data = _valid(s.ChangePasswordSerializer, request.data)
        user = request.user
        if not user.check_password(data["current_password"]):
            raise AppError("wrong_password")
        if data["current_password"] == data["new_password"]:
            raise AppError("same_password")
        try:
            validate_password(data["new_password"], user)
        except DjangoValidationError as exc:
            found = [arabic for english, arabic in contract.WEAK.items()
                     if any(english in str(m) for m in exc.messages)]
            raise AppError("weak_password", detail=" · ".join(found) or
                           contract.MESSAGES["weak_password"]) from None
        user.set_password(data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": contract.PASSWORD_CHANGED,
                         **tokens_for(self.member, request.auth.get(DEVICE_CLAIM))})


# --- the employee ----------------------------------------------------------------------------


def _today(person):
    day = services.work_day(person, timezone.now())
    return day, services.day_punches(person, day)


class MeView(AppView):
    def get(self, request):
        actor = request._request.actor
        person = _employee_or_none(self.member)
        unread = notifications.unread_count(self.member)
        if person is None:
            if not actor.can(MONITOR):
                raise AppError("no_employee", status=404)
            return Response({"username": self.member.username, "is_superuser": True,
                             "employee": None, "leave_balance": None, "today": [],
                             "active_session": None, "notifications_unread": unread})
        _day, punches = _today(person)
        return Response({
            "username": self.member.username, "is_superuser": actor.can(MONITOR),
            "employee": s.employee(person, request),
            "leave_balance": services.balance(person, timezone.localdate().year),
            "today": s.attendance_list(punches),
            "active_session": s.session(services.active_session(person)),
            "notifications_unread": unread})


class ConfigView(AppView):
    def get(self, request):
        return Response(services.config())


class ProfileView(AppView):
    def get(self, request):
        return Response(s.profile(self.employee(), request))

    def patch(self, request):
        person = self.employee()
        data = _valid(s.ProfileSerializer, request.data, partial=True)
        upload = request.FILES.get("image")
        if upload is not None and upload.size > s.MAX_IMAGE:
            raise AppError("image_too_large")
        fields = []
        if "tel" in data:
            person.phone, fields = data["tel"] or "", [*fields, "phone"]
        if "add" in data:
            person.address, fields = data["add"] or "", [*fields, "address"]
        if "image_base64" in data:
            extension, content = data["image_base64"]
            upload = ContentFile(content, name=f"photo-{get_random_string(12).lower()}"
                                               f".{extension}")
        if upload is not None:
            old = person.photo.name if person.photo else ""
            person.photo.save(upload.name, upload, save=False)
            fields.append("photo")
        if not fields:
            raise AppError("nothing_to_update")
        person.updated_by = request.user
        person.save(update_fields=[*fields, "updated_by", "updated_at"])
        if upload is not None and old:
            transaction.on_commit(lambda: person.photo.storage.delete(old))
        return Response(s.profile(person, request))


# --- the fingerprint proof -------------------------------------------------------------------


class EnrollView(AppView):
    def post(self, request):
        data = _valid(s.EnrollSerializer, request.data)
        enrollment, secret = services.enroll(self.employee(), data["device_id"],
                                             data["app_version"])
        return Response({"enrollment_id": enrollment.pk, "secret": secret,
                         "device_id": enrollment.device_id,
                         "enrolled_at": contract.moment(enrollment.enrolled_at)},
                        status=status.HTTP_201_CREATED)


class RevokeView(AppView):
    def post(self, request):
        services.revoke(self.employee())
        return Response(status=status.HTTP_204_NO_CONTENT)


class BiometricStatusView(AppView):
    def get(self, request):
        enrollment = services.active_enrollment(self.employee())
        return Response({"enrolled": enrollment is not None,
                         "enrollment_id": enrollment.pk if enrollment else None,
                         "device_id": enrollment.device_id if enrollment else None,
                         "enrolled_at": contract.moment(enrollment.enrolled_at)
                         if enrollment else None})


# --- attendance ------------------------------------------------------------------------------


class PunchView(AppView):
    def post(self, request):
        data = _valid(s.PunchSerializer, request.data)
        person = self.employee(status_code=400)
        record, session = services.punch(person, services.PunchInput(
            direction=int(data["status"]), latitude=data["latitude"],
            longitude=data["longitude"], device_id=data["device_id"],
            app_version=data["app_version"], tracking_enabled=data["tracking_enabled"],
            proof=data["biometric"]))
        return Response({"attendance": s.attendance(record, int(data["status"])),
                         "session": s.session(session),
                         "tracking": bool(session and session.is_active)},
                        status=status.HTTP_201_CREATED)


class TodayView(AppView):
    def get(self, request):
        person = self.employee()
        day, punches = _today(person)
        records = s.attendance_list(punches)
        session = services.active_session(person)
        return Response({
            "date": day.isoformat(),
            "check_in": next((r for r in records if r["status"] == 0), None),
            "check_out": next((r for r in reversed(records) if r["status"] == 1), None),
            "records": records, "tracking": session is not None,
            "session": s.session(session)})


def _date(text: str):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


class HistoryView(AppView):
    def get(self, request):
        person = self.employee()
        punches = person.punches.order_by("-at")
        start, end = _date(request.GET.get("from", "")), _date(request.GET.get("to", ""))
        zone = timezone.get_current_timezone()
        if start:
            punches = punches.filter(at__date__gte=start)
        if end:
            punches = punches.filter(at__date__lte=end)
        rows = list(punches[:500])
        by_day: dict = {}
        for punch in sorted(rows, key=lambda p: p.at):
            by_day.setdefault(punch.at.astimezone(zone).date(), []).append(punch)
        directions = {}
        for day_punches in by_day.values():
            directions.update(services.directions(day_punches))
        return Response([s.attendance(p, directions[p.pk]) for p in rows])


# --- leave -----------------------------------------------------------------------------------


def _year(request):
    raw = request.GET.get("year")
    return int(raw) if raw else None  # PayRole: a non-number fails (500); kept


class LeavesView(AppView):
    def get(self, request):
        return Response([s.leave(row) for row in services.leaves(self.employee(),
                                                                 _year(request))])

    def post(self, request):
        person = self.employee()
        data = _valid(s.LeaveCreateSerializer, request.data)
        row = services.ask_leave(person, self.member, data["date1"], data["date2"])
        return Response(s.leave(row), status=status.HTTP_201_CREATED)


class LeaveDetailView(AppView):
    def delete(self, request, ser):
        services.withdraw_leave(self.employee(status_code=400), self.member, ser)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaveBalanceView(AppView):
    def get(self, request):
        return Response(services.balance(self.employee(),
                                         _year(request) or timezone.localdate().year))


# --- notifications ---------------------------------------------------------------------------


class NotificationsView(AppView):
    def get(self, request):
        rows = notifications.for_member(self.member)
        if request.GET.get("unread") == "1":
            rows = rows.filter(read_at__isnull=True)
        before = request.GET.get("before", "")
        if before.isdigit():
            rows = rows.filter(pk__lt=int(before))
        items = list(rows.order_by("-pk")[:notifications.PAGE])
        return Response({
            "unread": notifications.unread_count(self.member),
            "items": [{"id": n.pk, "kind": n.kind, "title": n.title, "body": n.body,
                       "read": n.read_at is not None, "created_at": contract.moment(
                           n.created_at)} for n in items],
            "has_more": len(items) == notifications.PAGE})


class NotificationsReadView(AppView):
    def post(self, request):
        data = _valid(s.NotificationsReadSerializer, request.data)
        marked = notifications.mark_read(self.member, data["ids"] or None)
        return Response({"marked": marked, "unread": notifications.unread_count(self.member)})


# --- tracking --------------------------------------------------------------------------------


class TrackBatchView(AppView):
    def post(self, request):
        person = self.employee()
        data = _valid(s.TrackBatchSerializer, request.data)
        points = [dict(p) for p in data["points"]]
        saved, session = services.add_points(person, data["session_id"], points)
        return Response({"saved": saved, "received": len(points),
                         "session": s.session(session), "tracking": True})


class TrackStopView(AppView):
    def post(self, request):
        session = services.stop_session(self.employee(), "manual")
        return Response({"session": s.session(session), "tracking": False})


# --- following routes --------------------------------------------------------------------------


class MonitorView(AppView):
    permission_classes = [CanMonitor]

    def sessions(self):
        rows = TrackSession.objects.select_related("employee", "branch")
        allowed = self.request._request.actor.branch_ids(MONITOR)
        return rows if allowed is None else rows.filter(branch_id__in=allowed)


class MonitorLiveView(MonitorView):
    def get(self, request):
        services.close_stale()
        rows = []
        now = timezone.now()
        for session in self.sessions().filter(is_active=True).order_by("-started_at"):
            last = session.points.order_by("-recorded_at").first()
            if last is not None:
                position = {"lat": float(last.latitude), "lng": float(last.longitude),
                            "at": timezone.localtime(last.recorded_at).strftime("%H:%M"),
                            "battery": last.battery, "source": "track"}
                silent = int((now - last.recorded_at).total_seconds() // 60)
            elif session.check_in and session.check_in.latitude is not None:
                position = {"lat": float(session.check_in.latitude),
                            "lng": float(session.check_in.longitude),
                            "at": timezone.localtime(session.check_in.at).strftime("%H:%M"),
                            "battery": None, "source": "check_in"}
                silent = None
            else:
                position, silent = None, None
            rows.append({"session": s.monitor_session(session, request), "position": position,
                         "silent_minutes": silent})
        return Response({"interval_seconds": services.TRACK_INTERVAL_SECONDS, "rows": rows})


class MonitorSessionsView(MonitorView):
    def get(self, request):
        rows = self.sessions()
        key = request.GET.get("key", "").strip()
        if key:
            rows = rows.filter(employee__name__icontains=key)
        start, end = _date(request.GET.get("from", "")), _date(request.GET.get("to", ""))
        if start:
            rows = rows.filter(started_at__date__gte=start)
        if end:
            rows = rows.filter(started_at__date__lte=end)
        if request.GET.get("active") == "1":
            rows = rows.filter(is_active=True)
        rows = rows.order_by("-started_at")
        page = Paginator(rows, 20).get_page(request.GET.get("page"))
        totals = rows.aggregate(count=Count("pk"), active=Count("pk", filter=Q(is_active=True)),
                                distance=Sum("total_distance_m"), points=Sum("points_count"))
        return Response({
            "page": page.number, "pages": page.paginator.num_pages,
            "has_next": page.has_next(),
            "totals": {"count": totals["count"], "active": totals["active"],
                       "distance_m": float(totals["distance"] or 0),
                       "points": totals["points"] or 0},
            "results": [s.monitor_session(row, request) for row in page.object_list]})


class MonitorSessionView(MonitorView):
    def get(self, request, session_id):
        session = self.sessions().filter(pk=session_id).first()
        if session is None:
            raise AppError("not_found", detail=contract.MESSAGES["session_not_found"])
        route = [{"lat": float(p.latitude), "lng": float(p.longitude),
                  "at": timezone.localtime(p.recorded_at).strftime("%Y-%m-%d %H:%M:%S"),
                  "accuracy": float(p.accuracy_m) if p.accuracy_m is not None else None,
                  "battery": p.battery, "is_mock": p.is_mock}
                 for p in session.points.order_by("recorded_at")]

        def end(punch):
            if punch is None or punch.latitude is None:
                return None
            return {"lat": float(punch.latitude), "lng": float(punch.longitude),
                    "at": timezone.localtime(punch.at).strftime("%Y-%m-%d %H:%M")}

        return Response({"session": s.monitor_session(session, request), "route": route,
                         "endpoints": {"check_in": end(session.check_in),
                                       "check_out": end(session.check_out)},
                         "mock_count": sum(1 for p in route if p["is_mock"]),
                         "retention_days": services.TRACK_RETENTION_DAYS})
