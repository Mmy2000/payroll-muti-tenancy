"""The rules on leave requests and hourly leave, checked after what they read is locked."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.errors import DomainError, ValidationError, invalid_fields

from .domain.leave import leave_days, spans_overlap
from .models import DayKind, HourlyLeave, LeaveRequest
from .selectors import allowance, balance, minutes_used, overlapping_leave, working_day_test

# Kinds that may be entered for a day still to come (planning a day off or an excused absence).
PLANNABLE = {DayKind.EXCUSED, DayKind.DAY_OFF}

if TYPE_CHECKING:
    from .services.entries import DayEntryInput
    from .services.leave import LeaveRequestInput


def check_balance(request: LeaveRequest) -> None:
    if not request.leave_type.uses_annual_balance:
        return
    left = balance(request.employee, request.start_date.year)
    if not left.allows(request.days):
        raise DomainError(
            _("Only %(left)s days of annual leave are left this year; this request needs "
              "%(days)s.") % {"left": left.remaining, "days": request.days},
            code="ATTENDANCE_LEAVE_BALANCE")


def check_request(data: LeaveRequestInput, employee, leave_type) -> int:
    """The number of leave days, or the reasons the request can't be made."""
    errors = {}
    if leave_type is None:
        errors["leave_type_id"] = [_("Choose an active leave type.")]
    if data.end_date < data.start_date:
        errors["end_date"] = [_("Must not be before the first day.")]
    elif leave_type is not None and leave_type.uses_annual_balance and (
            data.start_date.year != data.end_date.year):
        errors["end_date"] = [_("Annual leave can't run into the next year; make two requests.")]
    elif data.start_date < employee.hired_on or (
            employee.left_on is not None and data.end_date > employee.left_on):
        errors["start_date"] = [_("The employee isn't employed on all these days.")]
    elif overlapping_leave(employee.pk, data.start_date, data.end_date).exists():
        errors["start_date"] = [_("Another request already covers some of these days.")]
    if errors:
        raise invalid_fields(errors)
    locks.ensure_open(employee.pk, data.start_date, data.end_date)
    days = leave_days(data.start_date, data.end_date, working_day_test(employee))
    if days == 0:
        raise invalid_fields({"end_date": [_("These are all days off or holidays: no leave is "
                                       "needed.")]})
    return days


def check_allowance(request: HourlyLeave) -> None:
    allowed = allowance(request.employee, request.work_date)
    used = minutes_used(request)
    if used + request.minutes > allowed:
        raise DomainError(
            _("This month's allowance is %(allowed)s minutes and %(used)s are used; this "
              "request needs %(minutes)s.")
            % {"allowed": allowed, "used": used, "minutes": request.minutes},
            code="ATTENDANCE_HOURLY_ALLOWANCE")


def check_spans(spans) -> None:
    errors = {}
    if not spans:
        errors["spans"] = [_("Enter at least one time span.")]
    for index, (start, end) in enumerate(spans):
        if start == end:
            errors[f"spans.{index}"] = [_("The end must be another time than the start.")]
        elif any(spans_overlap((start, end), other) for other in spans[:index]):
            errors[f"spans.{index}"] = [_("This overlaps an earlier span.")]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)


def check_day(data: DayEntryInput, work_date: date) -> None:
    errors = {}
    if data.kind not in DayKind.values:
        errors["kind"] = [_("Choose what happened that day.")]
    elif work_date > timezone.localdate() and data.kind not in PLANNABLE:
        errors["work_date"] = [_("Only a day off or an excused absence can be entered ahead.")]
    elif data.kind == DayKind.WORKED and not data.shift_times and data.check_in is None:
        errors["check_in"] = [_("Enter the time they came.")]
    if errors:
        raise invalid_fields(errors)


