"""A calculated run goes on: approved, paid, reversed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, DomainError, invalid_fields
from apps.core.events import publish
from apps.core.sequences import allocate_number
from apps.loans.services import advances as advance_services
from apps.loans.services import loans as loan_services

from ..events import RunPaid
from ..models import PaidSource, PayrollRun, PayslipLine, RunStatus
from ..permissions import APPROVE, PAY, REVERSE
from .runs import calculate_payslips, locked_run, require_draft

# What approval records as paid, and how each source is settled in its own app.
CONSUMED = ("compensation.PayItemAssignment", "adjustments.Adjustment", "loans.Advance",
            "loans.LoanInstallment")


def approve_run(run_id: int, *, actor=None) -> PayrollRun:
    with transaction.atomic():
        run = locked_run(run_id, actor, APPROVE)
        require_draft(run)
        calculate_payslips(run, actor)  # never approve stale figures
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
        run = locked_run(run_id, actor, PAY)
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
        run = locked_run(run_id, actor, REVERSE)
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
