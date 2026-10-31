"""What a member may see of payroll: runs of their scope, and the labels of what is in them."""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Q

from apps.core.history import in_effect
from apps.employees.selectors import visible_employees
from apps.org.models import Branch
from apps.org.selectors import visible_departments

from .domain.engine import ISSUES, LINE_LABELS
from .models import (
    LIVE,
    ManualLine,
    PaidSource,
    PayrollRun,
    Payslip,
    PayslipLine,
    PeriodKind,
    RunStatus,
    ScopeKind,
)
from .permissions import CALCULATE, READ


def visible_runs(actor):
    """Every run for a member reading payroll in all branches; otherwise the runs of their
    branches (a run for everyone or a department spans branches they can't see)."""
    runs = PayrollRun.objects.select_related("period")
    branches = actor.branch_ids(READ) if actor is not None else None
    if branches is None:
        return runs
    return runs.filter(Q(scope=ScopeKind.BRANCH) & Q(scope_id__in=branches))


def find_run(actor, pk):
    return visible_runs(actor).filter(pk=pk).first()


def runs_newest_first(actor):
    return visible_runs(actor).order_by("-period__start", "-id")


def runs_with_counts(actor):
    return runs_newest_first(actor).annotate(payslip_count=Count("payslips"))


def with_status(runs, value: str):
    return runs if value == "all" else runs.filter(status=value)


def scope_names(runs) -> dict:
    """{(scope, id): name} for the branches and departments the runs are for."""
    ids = {kind: {r.scope_id for r in runs if r.scope == kind}
           for kind in (ScopeKind.BRANCH, ScopeKind.DEPARTMENT)}
    names = {(ScopeKind.BRANCH, b.pk): b.name
             for b in Branch.objects.filter(pk__in=ids[ScopeKind.BRANCH])}
    names.update({(ScopeKind.DEPARTMENT, d.pk): d.label
                  for d in visible_departments().filter(pk__in=ids[ScopeKind.DEPARTMENT])})
    return names


def active_departments():
    return visible_departments().filter(is_active=True)


def visible_payslips(actor):
    return (Payslip.objects.filter(run__in=visible_runs(actor))
            .select_related("employee").prefetch_related("lines"))


def slips_by_code(run):
    return run.payslips.select_related("employee").order_by("employee__code")


def find_slip(run, pk):
    return run.payslips.select_related("employee").filter(pk=pk).first()


def slips_to_print(run):
    return run.payslips.select_related("employee__branch", "employee__department")


def find_slip_to_print(run, pk):
    return slips_to_print(run).filter(pk=pk).first()


def has_slips(run) -> bool:
    return slips_to_print(run).exists()


def labelled_lines(slip) -> list:
    lines = list(slip.lines.all())
    for line in lines:
        line.title = line_label(line)
    return lines


def manual_lines_for(run, employee):
    return run.manual_lines.filter(employee=employee).order_by("pk")


def manual_line_visible(actor, pk) -> bool:
    return ManualLine.objects.filter(pk=pk, run__in=visible_runs(actor)).exists()


def line_label(line) -> str:
    """"Incentive · Good month" for a named line of a system kind; the name or the kind alone
    otherwise."""
    kind = LINE_LABELS.get(line.code)
    if kind and line.label:
        return f"{kind} · {line.label}"
    return line.label or str(kind or line.code)


def issue_text(issue: dict) -> str:
    message = ISSUES.get(issue.get("code"))
    if message is None:
        return issue.get("code", "")
    try:
        return str(message) % issue.get("params", {})
    except (KeyError, TypeError, ValueError):
        return str(message)


def frequency_of(employee, day: date) -> str | None:
    pay = in_effect(employee.pay_history.all(), day)
    return pay.pay_frequency if pay else None


def candidates(run: PayrollRun, actor):
    """(employees to pay, the skipped with why) for the run's scope and frequency."""
    period = run.period
    people = visible_employees(actor, CALCULATE).filter(hired_on__lte=period.end).exclude(
        left_on__lt=period.start)
    if run.scope == ScopeKind.BRANCH:
        people = people.filter(branch_id=run.scope_id)
    elif run.scope == ScopeKind.DEPARTMENT:
        people = people.filter(department_id=run.scope_id)
    busy = {}
    if period.kind == PeriodKind.REGULAR:
        for slip in (Payslip.objects.filter(
                run__status__in=LIVE, run__period__kind=PeriodKind.REGULAR,
                run__period__frequency=period.frequency, run__period__start__lte=period.end,
                run__period__end__gte=period.start).exclude(run=run).select_related("run")):
            busy[slip.employee_id] = slip.run
    chosen, skipped = [], []
    for employee in people.select_related("branch").order_by("code"):
        last = period.end if employee.left_on is None else min(period.end, employee.left_on)
        if frequency_of(employee, last) != period.frequency:
            continue
        if employee.pk in busy:
            skipped.append({"employee_id": employee.pk, "name": employee.name,
                            "reason": "in_run", "run": str(busy[employee.pk])})
            continue
        chosen.append(employee)
    return chosen, skipped


def period_locked(employee_id: int, start: date, end: date) -> bool:
    return Payslip.objects.filter(
        employee_id=employee_id, run__status__in=(RunStatus.APPROVED, RunStatus.PAID),
        run__period__kind=PeriodKind.REGULAR, run__period__start__lte=end,
        run__period__end__gte=start).exists()


def source_locked(source: str, object_id: int) -> bool:
    if PaidSource.objects.filter(source=source, source_id=object_id, released=False).exists():
        return True
    return PayslipLine.objects.filter(
        source=source, source_id=object_id,
        payslip__run__status__in=(RunStatus.APPROVED, RunStatus.PAID)).exists()
