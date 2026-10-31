"""Payroll runs: creating and calculating them (docs/payroll-design.md §2–§3).

    draft ──approve──▶ approved ──pay──▶ paid
      │                   └──reverse──▶ reversed
      └──delete

A draft is calculated and recalculated freely. Approval recalculates, refuses while any payslip
has a blocking issue, numbers the run and records what it paid (`PaidSource`): installments
become paid, advances recovered, and nothing it paid can be paid again. A reversal releases all
of that. A paid run is corrected in a later run (manual lines).

A run covers employees of one pay frequency (their pay record at the period's end), in its
scope (everyone, a branch, a department) and the branches the member may run payroll for. An
employee already in another live regular run of an overlapping period is left out and listed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import (
    Conflict,
    DomainError,
    NotFound,
    invalid_fields,
)

from ..domain.engine import WARNING, calculate
from ..domain.inputs import OFF_CYCLE, REGULAR, to_snapshot
from ..domain.periods import Period
from ..gather import Gatherer
from ..models import (
    Frequency,
    ManualLine,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PayslipLine,
    PeriodKind,
    PeriodStatus,
    RunStatus,
    ScopeKind,
)
from ..permissions import CALCULATE
from ..selectors import candidates
from ..validators import require_scope
from .calendars import calendar_for, period_on

# --- calendars -----------------------------------------------------------------------------


# --- runs ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunInput:
    frequency: str
    kind: str = PeriodKind.REGULAR
    day: date | None = None  # regular: any day of the period
    start: date | None = None  # off-cycle
    end: date | None = None
    reason: str = ""
    scope: str = ScopeKind.ALL
    scope_id: int | None = None
    note: str = ""


def _period(data: RunInput) -> PayrollPeriod:
    if data.kind == PeriodKind.REGULAR:
        span = period_on(data.frequency, data.day or timezone.localdate())
        period, _created = PayrollPeriod.objects.get_or_create(
            frequency=data.frequency, kind=PeriodKind.REGULAR, start=span.start, end=span.end)
        return period
    if data.start is None or data.end is None or data.end < data.start:
        raise invalid_fields({"end": [_("Enter the first and last day of the off-cycle run.")]})
    if not data.reason.strip():
        raise invalid_fields({"reason": [_("Say why this off-cycle run is needed.")]})
    return PayrollPeriod.objects.create(frequency=data.frequency, kind=PeriodKind.OFF_CYCLE,
                                        start=data.start, end=data.end,
                                        reason=data.reason.strip())


def create_run(data: RunInput, *, actor=None) -> PayrollRun:
    if data.frequency not in Frequency.values:
        raise invalid_fields({"frequency": [_("Choose a pay frequency.")]})
    if data.kind not in PeriodKind.values:
        raise invalid_fields({"kind": [_("Choose a regular or an off-cycle run.")]})
    if data.scope not in ScopeKind.values or (data.scope != ScopeKind.ALL
                                             and data.scope_id is None):
        raise invalid_fields({"scope": [_("Choose who the run is for.")]})
    require_scope(actor, CALCULATE, data.scope, data.scope_id)
    with transaction.atomic():
        period = _period(data)
        if period.status == PeriodStatus.CLOSED:
            raise DomainError(_("This period is closed."), code="PAYROLL_PERIOD_CLOSED")
        run = PayrollRun.objects.create(period=period, scope=data.scope,
                                        scope_id=data.scope_id, note=data.note.strip(),
                                        created_by=getattr(actor, "user", None))
        calculate_payslips(run, actor)
    return run


def locked_run(run_id: int, actor, permission: str) -> PayrollRun:
    run = (PayrollRun.objects.select_for_update(of=("self",)).select_related("period")
           .filter(pk=run_id).first())
    if run is None:
        raise NotFound(_("Not found."))
    require_scope(actor, permission, run.scope, run.scope_id)
    return run


def require_draft(run: PayrollRun) -> None:
    if run.status != RunStatus.DRAFT:
        raise Conflict(_("Only a draft run can be changed."), code="PAYROLL_RUN_STATE")


def _period_of(run: PayrollRun) -> Period:
    return Period(run.period.start, run.period.end)


def gatherer_for(run: PayrollRun) -> Gatherer:
    kind = REGULAR if run.period.kind == PeriodKind.REGULAR else OFF_CYCLE
    calendar = calendar_for(run.period.frequency)
    return Gatherer(_period_of(run), kind, run.period.frequency, calendar, run.tenant_id)


def save_payslip(run: PayrollRun, employee, gatherer: Gatherer) -> Payslip | None:
    manual = list(ManualLine.objects.filter(run=run, employee=employee).order_by("pk"))
    data = gatherer.payslip_input(employee, manual)
    if data.employed is None:
        return None
    result = calculate(data)
    # Recalculated in place: a payslip keeps its id (and address) through a draft's life.
    slip, _created = Payslip.objects.update_or_create(run=run, employee=employee, defaults={
        "earnings": result.earnings, "deductions": result.deductions, "net": result.net,
        "employer_cost": result.employer_cost, "blocking": result.blocking,
        "warnings": sum(1 for i in result.issues if i.severity == WARNING),
        "issues": [{"severity": i.severity, "code": i.code, "params": i.params}
                   for i in result.issues],
        "snapshot": to_snapshot(data)})
    slip.lines.all().delete()
    PayslipLine.objects.bulk_create([
        PayslipLine(payslip=slip, position=position, code=line.code, kind=line.kind,
                    label=line.label, quantity=line.quantity, rate=line.rate,
                    amount=line.amount, taxable=line.taxable, source=line.source,
                    source_id=line.source_id, slice=line.slice)
        for position, line in enumerate(result.lines, start=1)])
    return slip


def totals(run: PayrollRun) -> None:
    slips = list(run.payslips.all())
    run.earnings = sum((s.earnings for s in slips), Decimal(0))
    run.deductions = sum((s.deductions for s in slips), Decimal(0))
    run.net = sum((s.net for s in slips), Decimal(0))
    run.employer_cost = sum((s.employer_cost for s in slips), Decimal(0))


def calculate_payslips(run: PayrollRun, actor) -> None:
    employees, skipped = candidates(run, actor)
    gatherer = gatherer_for(run)
    run.payslips.exclude(employee__in=employees).delete()
    for employee in employees:
        save_payslip(run, employee, gatherer)
    run.skipped = skipped
    run.calculated_at = timezone.now()
    totals(run)
    run.updated_by = getattr(actor, "user", None)
    run.save()


def calculate_run(run_id: int, *, actor=None) -> PayrollRun:
    """Recalculate a draft from today's data (rates, attendance, items…)."""
    with transaction.atomic():
        run = locked_run(run_id, actor, CALCULATE)
        require_draft(run)
        calculate_payslips(run, actor)
    return run


def delete_draft(run_id: int, *, actor=None) -> None:
    with transaction.atomic():
        run = locked_run(run_id, actor, CALCULATE)
        require_draft(run)
        period = run.period
        run.delete()
        if period.kind == PeriodKind.OFF_CYCLE and not period.runs.exists():
            period.delete()


# --- manual lines --------------------------------------------------------------------------


# --- approval, payment, reversal -----------------------------------------------------------


# --- locks for the other apps (apps.core.locks) --------------------------------------------


