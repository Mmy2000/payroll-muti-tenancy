"""The rules a loan must meet."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

from apps.core.errors import invalid_fields

from .domain.installments import CENT

if TYPE_CHECKING:
    from .services import LoanInput


MAX_INSTALLMENTS = 120


def check_loan(data: LoanInput, employee) -> None:
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
        raise invalid_fields(errors)
