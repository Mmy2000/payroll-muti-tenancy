"""Reading attendance: every day of a period for some employees, worked out by
apps.attendance.domain.days. Six queries whatever the number of employees and days; the rules
run in Python. The daily sheet, an employee's month and payroll all read attendance here."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.history import Timeline
from apps.core.tenancy.context import require_current_tenant_id
from apps.employees.models import WorkSchedule
from apps.platform.tenants import features
from apps.policies.models import PublicHoliday

from .approvals import ACTIVE
from .domain.days import DayFacts, DayResult, ManualEntry, Shift, evaluate_day
from .domain.leave import days_between
from .domain.workday import work_date_of
from .models import AttendanceDay, HourlyLeave, LeaveRequest, Punch, RequestStatus

# An employee's schedule rows, to find the one in effect on a day.
ScheduleHistory = Timeline


def _shift(row: WorkSchedule | None) -> Shift | None:
    if row is None:
        return None
    return Shift(row.starts_at, row.ends_at, frozenset(row.days_off), row.early_leave_minutes)


def holidays_between(start: date, end: date) -> dict[tuple[date, int | None], str]:
    """{(day, branch id or None for every branch): name}. None with the feature off: saved
    holidays then count as ordinary days."""
    if not features.is_enabled(require_current_tenant_id(), "public_holidays"):
        return {}
    return {(h.date, h.branch_id): h.name
            for h in PublicHoliday.objects.filter(date__range=(start, end))}


def holiday_name(holidays: dict, day: date, branch_id: int) -> str:
    return holidays.get((day, branch_id)) or holidays.get((day, None)) or ""


def evaluate(employees, start: date, end: date, *, today: date | None = None
             ) -> dict[int, list[DayResult]]:
    """{employee id: the DayResult of each day from `start` to `end`}."""
    tz = timezone.get_current_timezone()
    today = today or timezone.localdate()
    employees = list(employees)
    ids = [e.pk for e in employees]

    schedules = defaultdict(list)
    for row in WorkSchedule.objects.filter(employee_id__in=ids, effective_from__lte=end):
        schedules[row.employee_id].append(row)
    schedules = {pk: ScheduleHistory(rows) for pk, rows in schedules.items()}
    holidays = holidays_between(start, end)

    leave = defaultdict(dict)  # employee → {day: (type name, paid)}
    for request in (LeaveRequest.objects.filter(employee_id__in=ids,
                                                status=RequestStatus.APPROVED,
                                                start_date__lte=end, end_date__gte=start)
                    .select_related("leave_type")):
        for day in days_between(max(request.start_date, start), min(request.end_date, end)):
            leave[request.employee_id][day] = (request.leave_type.name, request.leave_type.paid)

    manual = {(d.employee_id, d.work_date): ManualEntry(d.kind, d.check_in, d.check_out)
              for d in AttendanceDay.objects.filter(employee_id__in=ids,
                                                    work_date__range=(start, end))}

    hourly = {(row["employee_id"], row["work_date"]): row["total"]
              for row in HourlyLeave.objects.filter(
                  employee_id__in=ids, status=RequestStatus.APPROVED,
                  work_date__range=(start, end))
              .values("employee_id", "work_date").annotate(total=Sum("minutes"))}

    punches = defaultdict(list)  # (employee, work day) → moments
    window = (datetime.combine(start - timedelta(days=1), time.min, tzinfo=tz),
              datetime.combine(end + timedelta(days=2), time.min, tzinfo=tz))
    for punch in Punch.objects.filter(employee_id__in=ids, at__range=window).only(
            "employee_id", "at"):
        local_day = punch.at.astimezone(tz).date()
        history = schedules.get(punch.employee_id)
        row = history.on(local_day) if history else None
        work_day = work_date_of(punch.at, row.starts_at, tz) if row else local_day
        punches[(punch.employee_id, work_day)].append(punch.at)

    results = {}
    for employee in employees:
        rows = schedules.get(employee.pk)
        days = []
        for day in days_between(start, end):
            leave_name, leave_paid = leave[employee.pk].get(day, ("", True))
            facts = DayFacts(
                day=day, today=today, tz=tz,
                employed=employee.hired_on <= day and (employee.left_on is None
                                                       or day <= employee.left_on),
                shift=_shift(rows.on(day) if rows else None),
                holiday=holiday_name(holidays, day, employee.branch_id),
                leave=leave_name, leave_paid=leave_paid,
                manual=manual.get((employee.pk, day)),
                punches=tuple(punches.get((employee.pk, day), ())),
                hourly_minutes=hourly.get((employee.pk, day), 0))
            days.append(evaluate_day(facts))
        results[employee.pk] = days
    return results


def working_day_test(employee):
    """A function telling whether a day is a working day for `employee`: not a weekly day off
    in the schedule of that day, and not a public holiday of their branch."""
    history = ScheduleHistory(employee.schedules.all())
    cache: dict[tuple[date, date], dict] = {}

    def is_working_day(day: date) -> bool:
        year = (date(day.year, 1, 1), date(day.year, 12, 31))
        holidays = cache.setdefault(year, holidays_between(*year))
        row = history.on(day)
        return (row is not None and day.weekday() not in row.days_off
                and not holiday_name(holidays, day, employee.branch_id))

    return is_working_day


def active_requests(model, employee_id: int):
    """Requests still holding days or hours (waiting or approved)."""
    return model.objects.filter(employee_id=employee_id, status__in=ACTIVE)


def overlapping_leave(employee_id: int, start: date, end: date, *, exclude: int | None = None):
    return (active_requests(LeaveRequest, employee_id)
            .filter(Q(start_date__lte=end) & Q(end_date__gte=start)).exclude(pk=exclude))
