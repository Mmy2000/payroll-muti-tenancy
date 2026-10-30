"""Loans recovered in monthly installments.

* One loan at a time: a new loan is refused while another still has installments due
  (PayRole: Loans/views.py GHC12a).
* A loan can be cancelled until one installment is paid; after that, only postponed.
* Postponing an installment moves it and every later due one a month on (PayRole: GHC13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, DomainError, NotFound, ValidationError
from apps.core.events import publish
from apps.core.months import add_months, months
from apps.employees.services import get_employee

from .domain.installments import CENT, split
from .events import LoanGranted
from .models import InstallmentStatus, Loan, LoanInstallment, LoanStatus

VIEW, MANAGE = "loans.loan.view", "loans.loan.manage"
MAX_INSTALLMENTS = 120


@dataclass(frozen=True)
class LoanInput:
    employee_id: int
    granted_on: date
    amount: Decimal
    installments: int
    first_month: date  # any day of the month the first installment is due
    reason: str = ""


def _invalid(fields: dict) -> ValidationError:
    return ValidationError(_("Please correct the highlighted fields."), fields=fields)


def _check(data: LoanInput, employee) -> None:
    errors = {}
    if data.amount <= 0:
        errors["amount"] = [_("Must be greater than zero.")]
    if not 1 <= data.installments <= MAX_INSTALLMENTS:
        errors["installments"] = [_("From 1 to %(count)s installments.")
                                  % {"count": MAX_INSTALLMENTS}]
    elif data.amount > 0 and data.amount < CENT * data.installments:
        # PayRole (Loans/views.py GHC12a): every installment is at least a piastre.
        errors["amount"] = [_("Too small for this many installments.")]
    if data.first_month.replace(day=1) < data.granted_on.replace(day=1):
        errors["first_month"] = [_("Must not be before the month the loan is given.")]
    if data.granted_on < employee.hired_on or (employee.left_on
                                               and data.granted_on > employee.left_on):
        errors["granted_on"] = [_("The employee isn't employed on that day.")]
    if errors:
        raise _invalid(errors)


def grant_loan(data: LoanInput, *, actor=None) -> Loan:
    with transaction.atomic():
        employee = get_employee(data.employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        _check(data, employee)
        if Loan.objects.filter(employee=employee, status=LoanStatus.ACTIVE).exists():
            raise DomainError(_("This employee is still repaying a loan."),
                              code="LOANS_ONE_AT_A_TIME")
        loan = Loan.objects.create(employee=employee, granted_on=data.granted_on,
                                   amount=data.amount, reason=data.reason.strip(),
                                   created_by=getattr(actor, "user", None))
        LoanInstallment.objects.bulk_create([
            LoanInstallment(loan=loan, number=number, due_month=month, amount=amount)
            for number, (month, amount) in enumerate(
                zip(months(data.first_month, data.installments),
                    split(data.amount, data.installments), strict=True), start=1)])
        publish(LoanGranted(loan=loan, installments=data.installments, by=actor))
    return loan


def _locked_loan(loan_id: int, actor) -> Loan:
    loan = Loan.objects.select_for_update().filter(pk=loan_id).first()
    if loan is None:
        raise NotFound(_("Not found."))
    employee = get_employee(loan.employee_id, actor, MANAGE)
    if actor is not None:
        actor.require(MANAGE, branch=employee.branch_id)
    return loan


def cancel_loan(loan_id: int, *, actor=None) -> Loan:
    with transaction.atomic():
        loan = _locked_loan(loan_id, actor)
        if loan.status != LoanStatus.ACTIVE:
            raise Conflict(_("This loan is no longer being repaid."), code="LOANS_LOAN_STATE")
        if loan.installments.filter(status=InstallmentStatus.PAID).exists():
            raise DomainError(_("Installments were already paid: postpone the rest instead."),
                              code="LOANS_LOAN_PARTLY_PAID")
        loan.installments.update(status=InstallmentStatus.CANCELLED)
        loan.status = LoanStatus.CANCELLED
        loan.updated_by = getattr(actor, "user", None)
        loan.save(update_fields=["status", "updated_by", "updated_at"])
        return loan


def postpone_installment(installment_id: int, *, actor=None) -> Loan:
    """Move a due installment, and every later due one, a month on. A paid installment can't be
    postponed (payroll paid it)."""
    with transaction.atomic():
        loan_id = LoanInstallment.objects.filter(pk=installment_id).values_list(
            "loan_id", flat=True).first()
        if loan_id is None:
            raise NotFound(_("Not found."))
        loan = _locked_loan(loan_id, actor)
        target = loan.installments.get(pk=installment_id)
        if target.status != InstallmentStatus.DUE:
            raise Conflict(_("Only a due installment can be postponed."),
                           code="LOANS_INSTALLMENT_STATE")
        for row in loan.installments.filter(status=InstallmentStatus.DUE,
                                            number__gte=target.number):
            row.due_month = add_months(row.due_month, 1)
            row.save(update_fields=["due_month", "updated_at"])
        return loan


def settle_installments(installment_ids, *, paid: bool) -> None:
    """Payroll approved (paid) or reversed (not paid) these installments. A loan whose
    installments are all paid is repaid; one with a due installment again is being repaid."""
    if not installment_ids:
        return
    rows = LoanInstallment.objects.filter(pk__in=list(installment_ids))
    loan_ids = set(rows.values_list("loan_id", flat=True))
    rows.update(status=InstallmentStatus.PAID if paid else InstallmentStatus.DUE)
    for loan in Loan.objects.filter(pk__in=loan_ids).select_for_update():
        due = loan.installments.filter(status=InstallmentStatus.DUE).exists()
        status = LoanStatus.ACTIVE if due else LoanStatus.SETTLED
        if loan.status != status and loan.status != LoanStatus.CANCELLED:
            loan.status = status
            loan.save(update_fields=["status", "updated_at"])
