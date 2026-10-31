"""Reading attendance: every day of a period for some employees, worked out by
apps.attendance.domain.days. Six queries whatever the number of employees and days; the rules
run in Python. The daily sheet, an employee's month and payroll all read attendance here."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.history import Timeline, in_effect
from apps.core.tenancy.context import require_current_tenant_id
from apps.employees.models import WorkSchedule
from apps.employees.selectors import employed_on, employee_rows, listed_employees
from apps.platform.tenants import features
from apps.policies.models import PublicHoliday

from .domain.days import DayFacts, DayResult, ManualEntry, Shift, evaluate_day
from .domain.leave import Balance, days_between, spans_overlap
from .domain.workday import work_date_of
from .models import AttendanceDay, HourlyLeave, LeaveRequest, LeaveType, Punch, RequestStatus
from .services.approvals import ACTIVE

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


def employees_of_day(actor, code: str, day: date, *, branch=None, department=None):
    """Who the daily sheet lists: employed on `day`, in `branch` and `department` if given."""
    people = listed_employees(actor, code).filter(employed_on(day))
    if branch:
        people = people.filter(branch=branch)
    if department:
        people = people.filter(department=department)
    return people


def visible_requests(model, actor, code: str, *, date_field: str, related=()):
    """Leave or hourly leave of the employees `actor` sees under `code`, the latest first."""
    return (employee_rows(model.objects.all(), actor, code, ("employee", *related))
            .order_by(f"-{date_field}", "-id"))


def leave_types():
    return LeaveType.objects.order_by("code")


def active_leave_types():
    return LeaveType.objects.filter(is_active=True)


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


def balance(employee, year: int) -> Balance:
    """Days counted against the annual balance in `year` (by the request's first day)."""
    pay = in_effect(employee.pay_history.all(), max(date(year, 1, 1), employee.hired_on))
    used = (LeaveRequest.objects.filter(employee=employee, leave_type__uses_annual_balance=True,
                                        start_date__year=year)
            .values("status").annotate(days=Sum("days")))
    by_status = {row["status"]: row["days"] for row in used}
    return Balance(entitled=pay.annual_leave_days if pay else 0,
                   taken=by_status.get(RequestStatus.APPROVED, 0),
                   requested=by_status.get(RequestStatus.PENDING, 0))


def minutes_used(request: HourlyLeave) -> int:
    month = HourlyLeave.objects.filter(
        employee=request.employee, status=RequestStatus.APPROVED,
        work_date__year=request.work_date.year, work_date__month=request.work_date.month)
    return month.aggregate(total=Sum("minutes"))["total"] or 0


def allowance(employee, day: date) -> int:
    pay = in_effect(employee.pay_history.all(), day)
    return int((pay.permission_hours if pay else 0) * 60)


def clashes(employee_id: int, work_date: date, starts_at: time, ends_at: time) -> bool:
    return any(spans_overlap((starts_at, ends_at), (row.starts_at, row.ends_at))
               for row in active_requests(HourlyLeave, employee_id).filter(work_date=work_date))
