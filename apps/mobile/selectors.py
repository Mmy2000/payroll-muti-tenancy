"""What the app reads: the day's punches, the phone's link, the open trip, the leave year."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.attendance.domain.workday import work_date_of
from apps.attendance.models import LeaveRequest, LeaveType, Punch, RequestStatus
from apps.attendance.selectors import ScheduleHistory
from apps.attendance.selectors import balance as attendance_balance
from apps.employees.models import Employee

from .contract import AppError
from .models import BiometricEnrollment


def day_punches(employee: Employee, day: date) -> list[Punch]:
    """The punches of one work day, oldest first."""
    zone = timezone.get_current_timezone()
    window = (datetime.combine(day - timedelta(days=1), datetime.min.time(), tzinfo=zone),
              datetime.combine(day + timedelta(days=2), datetime.min.time(), tzinfo=zone))
    return [p for p in Punch.objects.filter(employee=employee, at__range=window).order_by("at")
            if work_day(employee, p.at) == day]


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
