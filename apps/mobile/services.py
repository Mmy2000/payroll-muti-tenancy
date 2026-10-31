"""What the mobile app does (docs/mobile-api.md), in PayRole's order of checks and with its
messages (apps/mobile/contract.py), on this system's records:

* a punch is an attendance punch (source "mobile", with what the employee pressed and where),
  judged like the device's; its day is the employee's work day (a night shift's check-out after
  midnight belongs to the day it started; PayRole refused it);
* the fingerprint proof, GPS tracking and the geofence are the client's features;
* leave is a leave request of the annual leave type, with this system's balance and approval.

The app acts for the employee on their own records only, so the services below are trusted
callers of the attendance services (no actor), and say who asked (`by`).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.attendance import leave as leave_services
from apps.attendance.models import LeaveRequest, Punch, PunchSource, RequestStatus
from apps.core.crypto import decrypt, encrypt
from apps.core.errors import AppError as ServiceError
from apps.employees.models import Employee
from apps.platform.tenants import features

from .contract import MESSAGES, AppError, duplicate
from .models import BiometricEnrollment, BiometricNonce, EndReason, TrackPoint, TrackSession
from .selectors import active_enrollment, annual_type, balance, day_punches, work_day

TRACK_INTERVAL_SECONDS = 120
TRACK_DISTANCE_FILTER_M = 50
TRACK_BATCH_SIZE = 10
TRACK_MAX_SESSION_HOURS = 14
TRACK_RETENTION_DAYS = 14
PROOF_WINDOW_SECONDS = 120
NONCE_KEEP_SECONDS = PROOF_WINDOW_SECONDS * 5
EARTH_M = 6_371_000


def employee_of(member, *, status: int = 404) -> Employee:
    employee = getattr(member, "employee", None) if member is not None else None
    if employee is None or (employee.left_on and employee.left_on < timezone.localdate()):
        raise AppError("no_employee", status=status)
    return employee


def switched_on(key: str) -> bool:
    from apps.core.tenancy.context import require_current_tenant_id

    return features.is_enabled(require_current_tenant_id(), key)


def config() -> dict:
    return {"track_interval_seconds": TRACK_INTERVAL_SECONDS,
            "track_distance_filter_m": TRACK_DISTANCE_FILTER_M,
            "track_batch_size": TRACK_BATCH_SIZE,
            "track_max_session_hours": TRACK_MAX_SESSION_HOURS,
            "track_retention_days": TRACK_RETENTION_DAYS,
            "enforce_geofence": switched_on("geofence"),
            "tracking_required": switched_on("gps_tracking"),
            "biometric_required": switched_on("biometric")}


# --- work days and punches -------------------------------------------------------------------


def directions(punches: list[Punch]) -> dict[int, int]:
    """In (0) or out (1) for each punch: what the employee pressed, else first in, then out."""
    return {p.pk: p.direction if p.direction is not None else (0 if index == 0 else 1)
            for index, p in enumerate(punches)}


# --- the fingerprint proof -------------------------------------------------------------------


def enroll(employee: Employee, device_id: str, app_version: str = "") -> tuple:
    """A new phone for the employee's proofs; the earlier one stops working. Returns the
    enrollment and its secret (given once)."""
    now = timezone.now()
    with transaction.atomic():
        BiometricEnrollment.objects.filter(employee=employee, is_active=True).update(
            is_active=False, revoked_at=now, revoked_reason="reenroll")
        secret = secrets.token_hex(32)
        enrollment = BiometricEnrollment.objects.create(
            employee=employee, device_id=device_id, secret_encrypted=encrypt(secret),
            app_version=app_version)
    return enrollment, secret


def revoke(employee: Employee, reason: str = "signout") -> int:
    return BiometricEnrollment.objects.filter(employee=employee, is_active=True).update(
        is_active=False, revoked_at=timezone.now(), revoked_reason=reason)


def _proof_time(text: str) -> datetime | None:
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return timezone.make_aware(datetime.strptime(text, pattern))
        except ValueError:
            continue
    return None


def expected_proof(secret: str, enrollment_id: int, device_id: str, direction: int,
                   timestamp: str, nonce: str) -> str:
    message = f"{enrollment_id}|{device_id}|{direction}|{timestamp}|{nonce}"
    return hmac.new(bytes.fromhex(secret), message.encode(), hashlib.sha256).hexdigest()


def verify_proof(employee: Employee, direction: int, device_id: str, proof: dict | None) -> None:
    enrollment = active_enrollment(employee)
    if enrollment is None:
        raise AppError("biometric_not_enrolled")
    if not proof:
        raise AppError("biometric_required")
    if proof["enrollment_id"] != enrollment.pk:
        raise AppError("biometric_revoked")
    if (device_id or "") != enrollment.device_id:
        raise AppError("biometric_device_mismatch")
    stamped = _proof_time(proof["timestamp"])
    now = timezone.now()
    if stamped is None or abs((now - stamped).total_seconds()) > PROOF_WINDOW_SECONDS:
        raise AppError("biometric_stale")
    expected = expected_proof(decrypt(enrollment.secret_encrypted), enrollment.pk,
                              enrollment.device_id, direction, proof["timestamp"],
                              proof["nonce"])
    if not hmac.compare_digest(expected, proof["proof"]):
        raise AppError("biometric_invalid")
    BiometricNonce.objects.filter(used_at__lt=now - timedelta(seconds=NONCE_KEEP_SECONDS)
                                  ).delete()
    try:
        with transaction.atomic():
            BiometricNonce.objects.create(enrollment=enrollment, nonce=proof["nonce"])
    except IntegrityError:
        raise AppError("biometric_replay") from None
    enrollment.last_used_at = now
    enrollment.save(update_fields=["last_used_at", "updated_at"])


# --- the geofence ----------------------------------------------------------------------------


def distance_m(lat1, lng1, lat2, lng2) -> float:
    """Haversine, as PayRole measured tracks."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def _check_area(employee: Employee, latitude, longitude) -> None:
    branch = employee.branch
    if not switched_on("geofence") or branch.latitude is None or branch.longitude is None:
        return
    if latitude is None or longitude is None:
        raise AppError("location_required")
    if distance_m(branch.latitude, branch.longitude, latitude, longitude) > branch.radius_m:
        raise AppError("outside_geofence")


# --- punching --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PunchInput:
    direction: int
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    device_id: str = ""
    app_version: str = ""
    tracking_enabled: bool = False
    proof: dict | None = None


def punch(employee: Employee, data: PunchInput) -> tuple[Punch, TrackSession | None]:
    from apps.core import locks

    with transaction.atomic():
        employee = Employee.objects.select_for_update().select_related("branch").get(
            pk=employee.pk)
        if switched_on("biometric"):
            verify_proof(employee, data.direction, data.device_id, data.proof)
        if data.direction == 0 and switched_on("gps_tracking") and not data.tracking_enabled:
            raise AppError("tracking_required")
        _check_area(employee, data.latitude, data.longitude)
        now = timezone.now()
        today = work_day(employee, now)
        punches = day_punches(employee, today)
        same = [p for p in punches if p.source == PunchSource.MOBILE
                and p.direction == data.direction]
        if same:
            raise duplicate(data.direction, same[0].at)
        if data.direction == 1 and not punches:
            raise AppError("no_check_in")
        try:
            locks.ensure_open(employee.pk, today)
        except ServiceError as error:
            raise AppError(error.code.lower(), detail=error.message) from None
        record = Punch.objects.create(employee=employee, at=now, source=PunchSource.MOBILE,
                                      direction=data.direction, latitude=data.latitude,
                                      longitude=data.longitude)
        if data.direction == 0:
            session = start_session(employee, record, data.device_id, data.app_version)
        else:
            session = stop_session(employee, EndReason.CHECKOUT, check_out=record)
    return record, session


# --- tracking --------------------------------------------------------------------------------


def close_stale(employee: Employee | None = None) -> int:
    limit = timezone.now() - timedelta(hours=TRACK_MAX_SESSION_HOURS)
    sessions = TrackSession.objects.filter(is_active=True, started_at__lt=limit)
    if employee is not None:
        sessions = sessions.filter(employee=employee)
    closed = 0
    for session in sessions:
        session.is_active, session.end_reason = False, EndReason.TIMEOUT
        session.ended_at = session.started_at + timedelta(hours=TRACK_MAX_SESSION_HOURS)
        session.save(update_fields=["is_active", "end_reason", "ended_at", "updated_at"])
        closed += 1
    return closed


def start_session(employee: Employee, check_in: Punch, device_id: str = "",
                  app_version: str = "") -> TrackSession:
    now = timezone.now()
    TrackSession.objects.filter(employee=employee, is_active=True).update(
        is_active=False, ended_at=now, end_reason=EndReason.TIMEOUT)
    return TrackSession.objects.create(employee=employee, branch=employee.branch,
                                       check_in=check_in, started_at=check_in.at,
                                       device_id=device_id, app_version=app_version)


def stop_session(employee: Employee, reason: str, *, check_out: Punch | None = None
                 ) -> TrackSession | None:
    session = TrackSession.objects.filter(employee=employee, is_active=True).first()
    if session is None:
        return None
    session.is_active, session.end_reason = False, reason
    session.ended_at = check_out.at if check_out else timezone.now()
    session.check_out = check_out
    session.save(update_fields=["is_active", "end_reason", "ended_at", "check_out",
                                "updated_at"])
    return session


def add_points(employee: Employee, session_id: int | None, points: list[dict]
               ) -> tuple[int, TrackSession]:
    """Store a batch (points already stored at the same time are skipped) and measure the
    route again in time order (PayRole added each batch from its newest point, so a late batch
    lengthened the route)."""
    with transaction.atomic():
        if session_id is not None:
            session = (TrackSession.objects.select_for_update()
                       .filter(pk=session_id, employee=employee).first())
        else:
            close_stale(employee)
            session = (TrackSession.objects.select_for_update()
                       .filter(employee=employee, is_active=True).first())
        if session is None:
            raise AppError("no_active_session", tracking=False)
        if not session.is_active:
            raise AppError("session_closed", tracking=False)
        points = sorted(points, key=lambda p: p["recorded_at"])
        stored = set(session.points.filter(
            recorded_at__range=(points[0]["recorded_at"], points[-1]["recorded_at"]))
            .values_list("recorded_at", flat=True))
        fresh, seen = [], set(stored)
        for point in points:
            if point["recorded_at"] not in seen:
                seen.add(point["recorded_at"])
                fresh.append(TrackPoint(session=session, **point))
        TrackPoint.objects.bulk_create(fresh, ignore_conflicts=True)
        route = list(session.points.order_by("recorded_at").values_list("latitude",
                                                                       "longitude"))
        total = sum(distance_m(*a, *b) for a, b in zip(route, route[1:], strict=False))
        session.points_count = len(route)
        session.total_distance_m = Decimal(str(round(total, 2)))
        session.save(update_fields=["points_count", "total_distance_m", "updated_at"])
    return len(fresh), session


# --- leave -----------------------------------------------------------------------------------


def ask_leave(employee: Employee, member, start: date, end: date) -> LeaveRequest:
    """A request from the app is refused up front when the balance (waiting requests counted)
    can't cover it, as PayRole's was; the screens check it at approval."""
    from apps.attendance.domain.leave import leave_days
    from apps.attendance.selectors import working_day_test

    if not switched_on("leave"):
        raise AppError("leave_off", status=403)  # nobody could see or decide it
    leave_type = annual_type()
    days = leave_days(start, end, working_day_test(employee))
    left = balance(employee, start.year)
    if days > left["remaining"]:
        raise AppError("insufficient_balance", detail=MESSAGES["insufficient_balance"].format(
            left=left["remaining"], days=days))
    try:
        return leave_services.request_leave(leave_services.LeaveRequestInput(
            employee_id=employee.pk, leave_type_id=leave_type.pk, start_date=start,
            end_date=end), by=member)
    except ServiceError as error:
        raise AppError(error.code.lower(), detail=_first_message(error)) from None


def _first_message(error: ServiceError) -> str:
    for messages in error.fields.values():
        if messages:
            return str(messages[0])
    return error.message


def withdraw_leave(employee: Employee, member, pk: int) -> None:
    request = LeaveRequest.objects.filter(pk=pk, employee=employee).first()
    if request is None or request.status not in (RequestStatus.PENDING,
                                                 RequestStatus.APPROVED):
        raise AppError("not_found")
    if request.status == RequestStatus.APPROVED:
        raise AppError("already_accepted")
    try:
        leave_services.decide_leave(request.pk, "cancel", by=member)
    except ServiceError as error:
        raise AppError(error.code.lower(), detail=error.message) from None


def active_session(employee: Employee) -> TrackSession | None:
    close_stale(employee)
    return TrackSession.objects.filter(employee=employee, is_active=True).first()
