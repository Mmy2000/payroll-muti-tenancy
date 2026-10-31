"""What the app reads: the day's punches, the phone's link, the open trip, the leave year."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from apps.attendance.domain.workday import work_date_of
from apps.attendance.models import LeaveRequest, LeaveType, Punch, RequestStatus
from apps.attendance.selectors import ScheduleHistory
from apps.attendance.selectors import balance as attendance_balance
from apps.employees.models import Employee
from apps.platform.tenants import features

from .contract import AppError
from .models import BiometricEnrollment, TrackPoint, TrackSession


def day_punches(employee: Employee, day: date) -> list[Punch]:
    """The punches of one work day, oldest first."""
    zone = timezone.get_current_timezone()
    window = (datetime.combine(day - timedelta(days=1), datetime.min.time(), tzinfo=zone),
              datetime.combine(day + timedelta(days=2), datetime.min.time(), tzinfo=zone))
    return [p for p in Punch.objects.filter(employee=employee, at__range=window).order_by("at")
            if work_day(employee, p.at) == day]


def punch_history(employee: Employee, start: date | None, end: date | None) -> list[Punch]:
    """The latest 500, newest first."""
    punches = employee.punches.order_by("-at")
    if start:
        punches = punches.filter(at__date__gte=start)
    if end:
        punches = punches.filter(at__date__lte=end)
    return list(punches[:500])


def active_enrollment(employee: Employee) -> BiometricEnrollment | None:
    return BiometricEnrollment.objects.filter(employee=employee, is_active=True).first()


def annual_type() -> LeaveType:
    found = LeaveType.objects.filter(is_active=True, uses_annual_balance=True).order_by(
        "code").first()
    if found is None:
        raise AppError("no_leave_type")
    return found


def balance(employee: Employee, year: int) -> dict:
    """PayRole counted waiting requests as used too."""
    left = attendance_balance(employee, year)
    used = left.taken + left.requested
    return {"year": year, "allowed": left.entitled, "used": used,
            "remaining": left.entitled - used}


def leaves(employee: Employee, year: int | None):
    rows = LeaveRequest.objects.filter(
        employee=employee, status__in=(RequestStatus.PENDING, RequestStatus.APPROVED))
    if year:
        rows = rows.filter(start_date__year=year)
    return rows.order_by("-pk")


def work_day(employee: Employee, moment: datetime) -> date:
    local = timezone.localtime(moment)
    row = ScheduleHistory(employee.schedules.all()).on(local.date())
    return work_date_of(moment, row.starts_at, timezone.get_current_timezone()) if row \
        else local.date()


TRACK_INTERVAL_SECONDS = 120


TRACK_DISTANCE_FILTER_M = 50


TRACK_BATCH_SIZE = 10


TRACK_MAX_SESSION_HOURS = 14


TRACK_RETENTION_DAYS = 14


def employee_of(member, *, status: int = 404) -> Employee:
    employee = getattr(member, "employee", None) if member is not None else None
    if employee is None or (employee.left_on and employee.left_on < timezone.localdate()):
        raise AppError("no_employee", status=status)
    return employee


def linked_employee(member_id: int) -> Employee | None:
    return Employee.objects.filter(member_id=member_id).first()


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


def visible_sessions(actor, permission: str) -> QuerySet[TrackSession]:
    rows = TrackSession.objects.select_related("employee", "branch")
    allowed = actor.branch_ids(permission)
    return rows if allowed is None else rows.filter(branch_id__in=allowed)


def live_sessions(actor, permission: str) -> QuerySet[TrackSession]:
    return visible_sessions(actor, permission).filter(is_active=True).order_by("-started_at")


def search_sessions(actor, permission: str, *, key: str = "", start: date | None = None,
                    end: date | None = None, active_only: bool = False) -> QuerySet[TrackSession]:
    rows = visible_sessions(actor, permission)
    if key:
        rows = rows.filter(employee__name__icontains=key)
    if start:
        rows = rows.filter(started_at__date__gte=start)
    if end:
        rows = rows.filter(started_at__date__lte=end)
    if active_only:
        rows = rows.filter(is_active=True)
    return rows.order_by("-started_at")


def session_totals(rows: QuerySet[TrackSession]) -> dict:
    return rows.aggregate(count=Count("pk"), active=Count("pk", filter=Q(is_active=True)),
                          distance=Sum("total_distance_m"), points=Sum("points_count"))


def visible_session(actor, permission: str, session_id: int) -> TrackSession | None:
    return visible_sessions(actor, permission).filter(pk=session_id).first()


def last_point(session: TrackSession) -> TrackPoint | None:
    return session.points.order_by("-recorded_at").first()


def route_points(session: TrackSession) -> QuerySet[TrackPoint]:
    return session.points.order_by("recorded_at")
