"""The dashboard's figures (PayRole Main/views.py Home), each for members allowed to see what
it counts, in their branches:

* people: employees working, departments; new hires per month (24 months);
* attendance: today (present, absent, on leave) and those present each day (14 days), worked
  out like the daily sheet (PayRole counted punches only);
* payroll: the last approved period's net pay by department, net pay and overtime hours per
  month (12 months), from the frozen payslips of approved and paid runs (PayRole took the
  current month's, empty until it was paid);
* what is waiting (apps/notifications/selectors.py).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from apps.core.charts import Point, bars, columns, compact

PEOPLE, DAYS, PAYROLL = ("employees.employee.view", "attendance.day.view", "payroll.run.read")


def _months_back(today: date, count: int) -> list[date]:
    first = today.replace(day=1)
    months = []
    for _i in range(count):
        months.append(first)
        first = (first - timedelta(days=1)).replace(day=1)
    return list(reversed(months))


def _month(day: date) -> str:
    return formats.date_format(day, "M y")


def people(actor, today: date) -> dict:
    from apps.employees.selectors import visible_employees
    from apps.org.selectors import visible_departments

    staff = visible_employees(actor, PEOPLE)
    working = staff.exclude(left_on__lt=today)
    months = _months_back(today, 24)
    hires = dict(staff.filter(hired_on__gte=months[0], hired_on__lte=today)
                 .annotate(month=TruncMonth("hired_on")).values("month")
                 .annotate(n=Count("pk")).values_list("month", "n"))
    return {"working": working.count(),
            "departments": visible_departments(actor, PEOPLE).filter(is_active=True).count(),
            "hires": columns([Point(_month(m), hires.get(m, 0),
                                    title=formats.date_format(m, "F Y")) for m in months],
                               whole=True)}


def attendance(actor, today: date) -> dict:
    from apps.attendance.domain.days import Status
    from apps.attendance.selectors import evaluate
    from apps.employees.selectors import visible_employees

    start = today - timedelta(days=13)
    staff = list(visible_employees(actor, DAYS).filter(hired_on__lte=today).filter(
        Q(left_on__isnull=True) | Q(left_on__gte=start)))  # employed some day of the 14
    results = evaluate(staff, start, today, today=today)
    present = defaultdict(int)
    now = {"present": 0, "absent": 0, "leave": 0}
    for days in results.values():
        for day in days:
            if day.status == Status.PRESENT:
                present[day.day] += 1
        last = days[-1]
        if last.status == Status.PRESENT:
            now["present"] += 1
        elif last.status == Status.ABSENT:
            now["absent"] += 1
        elif last.status == Status.LEAVE:
            now["leave"] += 1
    span = [start + timedelta(days=i) for i in range(14)]
    return {**now, "present_days": columns([
        Point(formats.date_format(d, "j/n"), present.get(d, 0),
              title=formats.date_format(d, "l j F")) for d in span], whole=True)}


def _department(row: dict, rows) -> str:
    """A department's name; with its branch when another branch has one of the same name."""
    name = row["department__name"]
    if name is None:
        return _("No department")
    same = sum(1 for other in rows if other["department__name"] == name)
    return f"{name} · {row['department__branch__name']}" if same > 1 else name


def payroll(actor, today: date) -> dict | None:
    from apps.payroll.models import Payslip, PayslipLine, RunStatus
    from apps.payroll.selectors import visible_runs

    runs = visible_runs(actor).filter(status__in=(RunStatus.APPROVED, RunStatus.PAID))
    slips = Payslip.objects.filter(run__in=runs)
    latest = runs.order_by("-period__end").select_related("period").first()
    if latest is None:
        return None
    month = latest.period.end.replace(day=1)
    by_department = (slips.filter(run__period__end__year=month.year,
                                  run__period__end__month=month.month)
                     .values("department__name",
                             "department__branch__name").annotate(net=Sum("net")))
    months = _months_back(today, 12)
    net = dict(slips.filter(run__period__end__gte=months[0])
               .annotate(month=TruncMonth("run__period__end")).values("month")
               .annotate(total=Sum("net")).values_list("month", "total"))
    overtime = dict(PayslipLine.objects.filter(
        payslip__in=slips, code="overtime", payslip__run__period__end__gte=months[0])
        .annotate(month=TruncMonth("payslip__run__period__end")).values("month")
        .annotate(hours=Sum("quantity")).values_list("month", "hours"))
    total = sum((row["net"] for row in by_department), Decimal(0))
    return {
        "month": formats.date_format(month, "F Y"), "net": total, "net_text": compact(total),
        "by_department": bars([Point(_department(row, by_department), row["net"])
                               for row in by_department]),
        "net_months": columns([Point(_month(m), net.get(m, 0),
                                     title=formats.date_format(m, "F Y")) for m in months]),
        "overtime_months": columns([Point(_month(m), overtime.get(m) or 0,
                                          title=formats.date_format(m, "F Y"),
                                          shown=compact(overtime.get(m) or 0))
                                    for m in months]),
        "has_overtime": any(overtime.values())}


def figures(actor) -> dict:
    from apps.notifications.selectors import waiting

    today = timezone.localdate()
    found = {"waiting": waiting(actor)}
    if actor.can(PEOPLE):
        found["people"] = people(actor, today)
    if actor.can(DAYS):
        found["attendance"] = attendance(actor, today)
    if actor.can(PAYROLL):
        found["payroll"] = payroll(actor, today)
    return found


def employees_by_code(actor, permission: str):
    from apps.employees.selectors import visible_employees

    return visible_employees(actor, permission).order_by("code")
