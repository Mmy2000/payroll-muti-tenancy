"""Payroll: calendars, runs and their workflow (docs/payroll-design.md §2–§3).

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

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import (
    Conflict,
    DomainError,
    NotFound,
    PermissionDenied,
    invalid_fields,
)
from apps.core.events import publish
from apps.core.sequences import allocate_number
from apps.loans import advances as advance_services
from apps.loans import services as loan_services

from .domain import periods as period_rules
from .domain.engine import WARNING, calculate
from .domain.inputs import OFF_CYCLE, REGULAR, to_snapshot
from .domain.periods import Period
from .events import RunPaid
from .gather import Gatherer
from .models import (
    LIVE,
    Frequency,
    ManualLine,
    MonthlyRule,
    PaidSource,
    PayCalendar,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PayslipLine,
    PeriodKind,
    PeriodStatus,
    RunStatus,
    ScopeKind,
)
from .permissions import APPROVE, CALCULATE, PAY, REVERSE, SETUP
from .selectors import candidates

DEFAULT_ANCHOR = date(2026, 1, 3)  # a Saturday: weeks run Saturday to Friday until changed


# --- calendars -----------------------------------------------------------------------------


def calendar_for(frequency: str) -> PayCalendar:
    calendar, _created = PayCalendar.objects.get_or_create(
        frequency=frequency,
        defaults={"anchor": None if frequency == Frequency.MONTHLY else DEFAULT_ANCHOR})
    return calendar


@dataclass(frozen=True)
class CalendarInput:
    frequency: str
    start_day: int = 1
    anchor: date | None = None
    monthly_items: str = MonthlyRule.SPLIT


def save_calendar(data: CalendarInput, *, actor=None) -> PayCalendar:
    """Change how a frequency's periods fall; refused once runs of it exist, as their periods
    would no longer line up. Calendars are the whole company's: every branch is needed."""
    _require_scope(actor, SETUP, ScopeKind.ALL, None)
    errors = {}
    if data.frequency not in Frequency.values:
        errors["frequency"] = [_("Choose a pay frequency.")]
    elif data.frequency == Frequency.MONTHLY and not 1 <= data.start_day <= 28:
        errors["start_day"] = [_("Choose a day from 1 to 28.")]
    elif data.frequency != Frequency.MONTHLY and data.anchor is None:
        errors["anchor"] = [_("Enter the first day of one pay period.")]
    if data.monthly_items not in MonthlyRule.values:
        errors["monthly_items"] = [_("Choose from the list.")]
    if errors:
        raise invalid_fields(errors)
    with transaction.atomic():
        calendar = PayCalendar.objects.select_for_update().filter(pk=calendar_for(
            data.frequency).pk).get()
        moved = (calendar.start_day != data.start_day or calendar.anchor != data.anchor)
        if moved and PayrollRun.objects.filter(period__frequency=data.frequency,
                                               period__kind=PeriodKind.REGULAR,
                                               status__in=LIVE).exists():
            raise DomainError(_("Runs already exist for this pay frequency: its periods can't "
                                "move any more."), code="PAYROLL_CALENDAR_IN_USE")
        calendar.start_day = data.start_day if data.frequency == Frequency.MONTHLY else 1
        calendar.anchor = data.anchor if data.frequency != Frequency.MONTHLY else None
        calendar.monthly_items = data.monthly_items
        calendar.updated_by = getattr(actor, "user", None)
        calendar.save()
    return calendar


def period_on(frequency: str, day: date) -> Period:
    calendar = calendar_for(frequency)
    return period_rules.period_containing(day, frequency, start_day=calendar.start_day,
                                          anchor=calendar.anchor)


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


def _require_scope(actor, permission: str, run_scope: str, scope_id: int | None) -> None:
    """A branch run needs the permission in that branch; any other, in every branch."""
    if actor is None:
        return
    if run_scope == ScopeKind.BRANCH:
        actor.require(permission, branch=scope_id)
    elif actor.branch_ids(permission) is not None:
        raise PermissionDenied(_("This needs the permission in every branch."),
                               code="PAYROLL_ALL_BRANCHES")
    else:
        actor.require(permission)


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
    _require_scope(actor, CALCULATE, data.scope, data.scope_id)
    with transaction.atomic():
        period = _period(data)
        if period.status == PeriodStatus.CLOSED:
            raise DomainError(_("This period is closed."), code="PAYROLL_PERIOD_CLOSED")
        run = PayrollRun.objects.create(period=period, scope=data.scope,
                                        scope_id=data.scope_id, note=data.note.strip(),
                                        created_by=getattr(actor, "user", None))
        _calculate(run, actor)
    return run


def _locked_run(run_id: int, actor, permission: str) -> PayrollRun:
    run = (PayrollRun.objects.select_for_update(of=("self",)).select_related("period")
           .filter(pk=run_id).first())
    if run is None:
        raise NotFound(_("Not found."))
    _require_scope(actor, permission, run.scope, run.scope_id)
    return run


def _require_draft(run: PayrollRun) -> None:
    if run.status != RunStatus.DRAFT:
        raise Conflict(_("Only a draft run can be changed."), code="PAYROLL_RUN_STATE")


def _period_of(run: PayrollRun) -> Period:
    return Period(run.period.start, run.period.end)


def _gatherer(run: PayrollRun) -> Gatherer:
    kind = REGULAR if run.period.kind == PeriodKind.REGULAR else OFF_CYCLE
    calendar = calendar_for(run.period.frequency)
    return Gatherer(_period_of(run), kind, run.period.frequency, calendar, run.tenant_id)


def _save_payslip(run: PayrollRun, employee, gatherer: Gatherer) -> Payslip | None:
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


def _totals(run: PayrollRun) -> None:
    slips = list(run.payslips.all())
    run.earnings = sum((s.earnings for s in slips), Decimal(0))
    run.deductions = sum((s.deductions for s in slips), Decimal(0))
    run.net = sum((s.net for s in slips), Decimal(0))
    run.employer_cost = sum((s.employer_cost for s in slips), Decimal(0))


def _calculate(run: PayrollRun, actor) -> None:
    employees, skipped = candidates(run, actor)
    gatherer = _gatherer(run)
    run.payslips.exclude(employee__in=employees).delete()
    for employee in employees:
        _save_payslip(run, employee, gatherer)
    run.skipped = skipped
    run.calculated_at = timezone.now()
    _totals(run)
    run.updated_by = getattr(actor, "user", None)
    run.save()


def calculate_run(run_id: int, *, actor=None) -> PayrollRun:
    """Recalculate a draft from today's data (rates, attendance, items…)."""
    with transaction.atomic():
        run = _locked_run(run_id, actor, CALCULATE)
        _require_draft(run)
        _calculate(run, actor)
    return run


def delete_draft(run_id: int, *, actor=None) -> None:
    with transaction.atomic():
        run = _locked_run(run_id, actor, CALCULATE)
        _require_draft(run)
        period = run.period
        run.delete()
        if period.kind == PeriodKind.OFF_CYCLE and not period.runs.exists():
            period.delete()


# --- manual lines --------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualLineInput:
    employee_id: int
    label: str
    amount: Decimal
    addition: bool = True
    taxable: bool = True


def add_manual_line(run_id: int, data: ManualLineInput, *, actor=None) -> Payslip:
    with transaction.atomic():
        run = _locked_run(run_id, actor, CALCULATE)
        _require_draft(run)
        employee = run.payslips.filter(employee_id=data.employee_id).select_related(
            "employee").first()
        if employee is None:
            raise invalid_fields({"employee_id": [_("This employee isn't in the run.")]})
        if not data.label.strip():
            raise invalid_fields({"label": [_("Say what the line is for.")]})
        if data.amount <= 0:
            raise invalid_fields({"amount": [_("Must be greater than zero.")]})
        ManualLine.objects.create(run=run, employee_id=data.employee_id,
                                  label=data.label.strip(), amount=data.amount,
                                  addition=data.addition, taxable=data.taxable,
                                  created_by=getattr(actor, "user", None))
        slip = _save_payslip(run, employee.employee, _gatherer(run))
        _totals(run)
        run.save()
        return slip


def remove_manual_line(line_id: int, *, actor=None) -> Payslip:
    with transaction.atomic():
        line = ManualLine.objects.filter(pk=line_id).first()
        if line is None:
            raise NotFound(_("Not found."))
        run = _locked_run(line.run_id, actor, CALCULATE)
        _require_draft(run)
        employee = line.employee
        line.delete()
        slip = _save_payslip(run, employee, _gatherer(run))
        _totals(run)
        run.save()
        return slip


# --- approval, payment, reversal -----------------------------------------------------------

# What approval records as paid, and how each source is settled in its own app.
CONSUMED = ("compensation.PayItemAssignment", "adjustments.Adjustment", "loans.Advance",
            "loans.LoanInstallment")


def approve_run(run_id: int, *, actor=None) -> PayrollRun:
    with transaction.atomic():
        run = _locked_run(run_id, actor, APPROVE)
        _require_draft(run)
        _calculate(run, actor)  # never approve stale figures
        if not run.payslips.exists():
            raise DomainError(_("Nobody to pay in this run."), code="PAYROLL_EMPTY")
        blocked = run.payslips.filter(blocking__gt=0).count()
        if blocked:
            raise DomainError(
                _("%(count)s payslips have problems to solve before approval.")
                % {"count": blocked}, code="PAYROLL_BLOCKING_ISSUES")
        lines = PayslipLine.objects.filter(payslip__run=run, source__in=CONSUMED)
        try:
            with transaction.atomic():
                PaidSource.objects.bulk_create([
                    PaidSource(payslip_id=line.payslip_id, source=line.source,
                               source_id=line.source_id, slice=line.slice) for line in lines])
        except IntegrityError:
            raise Conflict(_("Another run paid some of this meanwhile. Recalculate and try "
                             "again."), code="PAYROLL_ALREADY_PAID") from None
        ids = {source: [line.source_id for line in lines if line.source == source]
               for source in CONSUMED}
        loan_services.settle_installments(ids["loans.LoanInstallment"], paid=True)
        advance_services.settle_advances(ids["loans.Advance"], recovered=True)
        run.number = allocate_number("PR", branch=None, fiscal_year=run.period.end.year)
        run.status = RunStatus.APPROVED
        run.approved_at, run.approved_by = timezone.now(), getattr(actor, "user", None)
        run.save(update_fields=["number", "status", "approved_at", "approved_by", "updated_at"])
    return run


@dataclass(frozen=True)
class PaymentInput:
    paid_on: date
    method: str = ""
    reference: str = ""


def record_payment(run_id: int, data: PaymentInput, *, actor=None) -> PayrollRun:
    with transaction.atomic():
        run = _locked_run(run_id, actor, PAY)
        if run.status != RunStatus.APPROVED:
            raise Conflict(_("Only an approved run can be paid."), code="PAYROLL_RUN_STATE")
        run.status, run.paid_on = RunStatus.PAID, data.paid_on
        run.payment_method, run.payment_reference = data.method.strip(), data.reference.strip()
        run.paid_by = getattr(actor, "user", None)
        run.save(update_fields=["status", "paid_on", "payment_method", "payment_reference",
                                "paid_by", "updated_at"])
        publish(RunPaid(run=run, by=actor))
    return run


def reverse_run(run_id: int, reason: str, *, actor=None) -> PayrollRun:
    """Undo an approved (not paid) run: what it paid is released, its payslips stay on record."""
    if not reason.strip():
        raise invalid_fields({"reason": [_("Say why the run is reversed.")]})
    with transaction.atomic():
        run = _locked_run(run_id, actor, REVERSE)
        if run.status != RunStatus.APPROVED:
            raise Conflict(_("Only an approved run that isn't paid yet can be reversed; correct a "
                             "paid one in a later run."), code="PAYROLL_RUN_STATE")
        sources = PaidSource.objects.filter(payslip__run=run, released=False)
        ids = {source: list(sources.filter(source=source).values_list("source_id", flat=True))
               for source in CONSUMED}
        sources.update(released=True)
        loan_services.settle_installments(ids["loans.LoanInstallment"], paid=False)
        advance_services.settle_advances(ids["loans.Advance"], recovered=False)
        run.status = RunStatus.REVERSED
        run.reversed_at, run.reversed_by = timezone.now(), getattr(actor, "user", None)
        run.reversal_reason = reason.strip()
        run.save(update_fields=["status", "reversed_at", "reversed_by", "reversal_reason",
                                "updated_at"])
    return run


# --- locks for the other apps (apps.core.locks) --------------------------------------------


