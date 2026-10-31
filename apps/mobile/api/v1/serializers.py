"""The app's objects as it reads them (docs/mobile-api.md "Objects"), and what it sends,
validated with DRF's own messages as PayRole's were."""
from __future__ import annotations

import base64
import binascii
import re

from django.utils import timezone
from rest_framework import exceptions, serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from apps.employees.models import Weekday

from ... import contract
from ...contract import day, decimal, moment
from ...services import devices
from ...services import punches as punches_services
from .auth import DEVICE_CLAIM, TENANT_CLAIM, active_membership

DAY_CODES = {Weekday.MONDAY: "mo", Weekday.TUESDAY: "tu", Weekday.WEDNESDAY: "we",
             Weekday.THURSDAY: "th", Weekday.FRIDAY: "fr", Weekday.SATURDAY: "sa",
             Weekday.SUNDAY: "su"}
MAX_IMAGE = 5 * 1024 * 1024


def absolute(request, file) -> str | None:
    if not file:
        return None
    url = file.url
    return request.build_absolute_uri(url) if request is not None else url


def days_off(employee) -> str | None:
    from apps.attendance.selectors import ScheduleHistory

    row = ScheduleHistory(employee.schedules.all()).on(timezone.localdate())
    if row is None or not row.days_off:
        return None
    return ",".join(DAY_CODES[Weekday(d)] for d in sorted(row.days_off))


def employee(person, request) -> dict | None:
    if person is None:
        return None
    return {"eco": person.code, "name": person.name,
            "branch_code": person.branch.code if person.branch_id else None,
            "branch_name": person.branch.name if person.branch_id else None,
            "group": person.department.name if person.department_id else None,
            "photo": absolute(request, person.photo), "day_off": days_off(person)}


def attendance(punch, direction: int) -> dict:
    return {"id": punch.pk, "date": day(timezone.localtime(punch.at).date()),
            "timestamp": moment(punch.at), "status": direction,
            "status_text": contract.STATUS_TEXT[direction],
            "latitude": decimal(punch.latitude, 6), "longitude": decimal(punch.longitude, 6)}


def attendance_list(punches) -> list[dict]:
    directions = punches_services.directions(punches)
    return [attendance(p, directions[p.pk]) for p in punches]


def session(row) -> dict | None:
    if row is None:
        return None
    return {"id": row.pk, "started_at": moment(row.started_at), "ended_at": moment(row.ended_at),
            "is_active": row.is_active, "end_reason": row.end_reason or None,
            "points_count": row.points_count, "total_distance_m": decimal(row.total_distance_m),
            "duration_minutes": row.duration_minutes}


def monitor_session(row, request) -> dict:
    data = session(row)
    person = row.employee
    data.update(end_reason_text=contract.END_REASON_TEXT.get(row.end_reason),
                app_version=row.app_version, branch_name=row.branch.name,
                employee={"eco": person.code, "name": person.name,
                          "photo": absolute(request, person.photo)})
    return data


def leave(request_row) -> dict:
    approved = request_row.status == "approved"
    return {"ser": request_row.pk, "date": day(request_row.created_at.date()),
            "date1": day(request_row.start_date), "date2": day(request_row.end_date),
            "days": request_row.days, "acept": approved,
            "status_text": contract.LEAVE_TEXT[approved]}


def masked(value: str) -> str | None:
    if not value or not value.isdigit():
        return None
    return "*" * (len(value) - 4) + value[-4:]


def profile(person, request) -> dict:
    from apps.core.history import in_effect

    pay = in_effect(person.pay_history.all(), timezone.localdate())
    return {"tel": person.phone or None, "add": person.address or None,
            "photo": absolute(request, person.photo), "eco": person.code, "name": person.name,
            "branch_name": person.branch.name if person.branch_id else None,
            "group": person.department.name if person.department_id else None,
            "job_title": person.job_title or None, "hire_date": day(person.hired_on),
            "birth_date": day(person.birth_date), "national_id": masked(person.national_id),
            "day_off": days_off(person),
            "annual_leave": pay.annual_leave_days if pay else None}


# --- what the app sends -------------------------------------------------------------------------


class QrLoginSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=100)
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True,
                                      default="")


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True,
                                      default="")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)
    confirm_password = serializers.CharField()

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(contract.PASSWORDS_DIFFER)
        return attrs


class ProfileSerializer(serializers.Serializer):
    tel = serializers.CharField(max_length=20, required=False, allow_blank=True,
                                allow_null=True)
    add = serializers.CharField(max_length=100, required=False, allow_blank=True,
                                allow_null=True)
    image_base64 = serializers.CharField(required=False)

    def validate_tel(self, value):
        if not value:
            return ""
        value = value.strip().replace(" ", "")
        if not re.fullmatch(r"\+?\d{7,15}", value):
            raise serializers.ValidationError(contract.BAD_PHONE)
        if value.startswith("01"):
            return "+2" + value
        return value if value.startswith("+") else "+" + value

    def validate_image_base64(self, value):
        match = re.fullmatch(r"data:image/(\w+);base64,(.*)", value, re.S)
        extension, data = (match.group(1).lower(), match.group(2)) if match else ("jpg", value)
        if extension not in ("jpg", "jpeg", "png", "webp"):
            raise serializers.ValidationError("صيغة صورة غير مدعومة")
        try:
            content = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise serializers.ValidationError("تعذّر قراءة الصورة") from None
        if not content:
            raise serializers.ValidationError("الصورة فارغة")
        if len(content) > MAX_IMAGE:
            raise serializers.ValidationError(contract.MESSAGES["image_too_large"])
        return ("jpg" if extension == "jpeg" else extension, content)


class EnrollSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=100)
    app_version = serializers.CharField(max_length=20, required=False, allow_blank=True,
                                        default="")


class ProofSerializer(serializers.Serializer):
    enrollment_id = serializers.IntegerField()
    timestamp = serializers.CharField(max_length=32)
    nonce = serializers.CharField(max_length=64)
    proof = serializers.CharField(max_length=64)


class PunchSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[(0, 0), (1, 1)])
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False,
                                        allow_null=True, default=None)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False,
                                         allow_null=True, default=None)
    accuracy_m = serializers.DecimalField(max_digits=8, decimal_places=2, required=False,
                                          allow_null=True, default=None)
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True,
                                      default="")
    app_version = serializers.CharField(max_length=20, required=False, allow_blank=True,
                                        default="")
    tracking_enabled = serializers.BooleanField(required=False, default=False)
    biometric = ProofSerializer(required=False, default=None)


class LeaveCreateSerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    date1 = serializers.DateField()
    date2 = serializers.DateField()
    days = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        if attrs["date2"] < attrs["date1"]:
            raise serializers.ValidationError(contract.LEAVE_ENDS_FIRST)
        return attrs


class NotificationsReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), required=False,
                                default=list)


class PointSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = serializers.DecimalField(max_digits=8, decimal_places=2, required=False,
                                          allow_null=True, default=None)
    speed = serializers.DecimalField(max_digits=8, decimal_places=2, required=False,
                                     allow_null=True, default=None)
    heading = serializers.DecimalField(max_digits=6, decimal_places=2, required=False,
                                       allow_null=True, default=None)
    battery = serializers.IntegerField(required=False, allow_null=True, default=None)
    recorded_at = serializers.DateTimeField()
    is_mock = serializers.BooleanField(required=False, default=False)


class TrackBatchSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    points = PointSerializer(many=True, allow_empty=False)

    def validate_points(self, value):
        if len(value) > 500:
            raise serializers.ValidationError(contract.TOO_MANY_POINTS)
        return value


class TenantRefreshSerializer(TokenRefreshSerializer):
    """A refresh token works on the client it was issued for, for a member still active."""

    def validate(self, attrs):
        request = self.context["request"]
        token = RefreshToken(attrs["refresh"])  # TokenError: "Token is invalid" (401)
        tenant = getattr(request._request, "tenant", None)
        if tenant is None or token.get(TENANT_CLAIM) != tenant.id:
            raise TokenError("Token is invalid")
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=token.get("user_id")).first()
        device_pk = token.get(DEVICE_CLAIM)
        if (user is None or active_membership(user) is None
                or (device_pk is not None and not devices.is_allowed(device_pk))):
            raise exceptions.AuthenticationFailed(
                "No active account found for the given token.")
        if device_pk is not None:
            devices.seen(device_pk)
        return super().validate(attrs)


