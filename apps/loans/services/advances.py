"""Salary advances: part of a month's pay given early, recovered by that month's payroll.

The month's advances may not add up to more than a month's pay (PayRole: Loans/views.py
GHC11a). Permissions follow the employee's branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, DomainError, NotFound, ValidationError
from apps.core.events import publish
from apps.core.history import in_effect
from apps.employees.selectors import get_employee

from ..events import AdvanceGiven
from ..models import Advance, AdvanceStatus
from ..permissions import ADVANCE_MANAGE
from ..selectors import month_advances


@dataclass(frozen=True)
class AdvanceInput:
    employee_id: int
    date: date
    amount: Decimal
    reason: str = ""


def give_advance(data: AdvanceInput, *, actor=None) -> Advance:
    with transaction.atomic():
        employee = get_employee(data.employee_id, actor, ADVANCE_MANAGE, lock=True)
        if actor is not None:
            actor.require(ADVANCE_MANAGE, branch=employee.branch_id)
        if data.amount <= 0:
            raise ValidationError(_("Please correct the highlighted fields."),
                                  fields={"amount": [_("Must be greater than zero.")]})
        if data.date < employee.hired_on or (employee.left_on and data.date > employee.left_on):
            raise ValidationError(_("Please correct the highlighted fields."),
                                  fields={"date": [_("The employee isn't employed on that day.")]})
        pay = in_effect(employee.pay_history.all(), data.date)
        limit = pay.terms.monthly if pay else Decimal(0)
        already = month_advances(employee, data.date)
        if already + data.amount > limit:
            raise DomainError(
                _("Advances this month would come to %(total)s, more than a month's pay "
                  "(%(limit)s).") % {"total": already + data.amount, "limit": limit},
                code="LOANS_ADVANCE_LIMIT")
        advance = Advance.objects.create(employee=employee, date=data.date, amount=data.amount,
                                         reason=data.reason.strip(),
                                         created_by=getattr(actor, "user", None))
        publish(AdvanceGiven(advance=advance, by=actor))
        return advance


def settle_advances(advance_ids, *, recovered: bool) -> None:
    """Payroll approved (recovered) or reversed (open again) these advances."""
    if advance_ids:
        Advance.objects.filter(pk__in=list(advance_ids)).exclude(
            status=AdvanceStatus.CANCELLED).update(
            status=AdvanceStatus.RECOVERED if recovered else AdvanceStatus.OPEN)


def cancel_advance(advance_id: int, *, actor=None) -> Advance:
    """Only an advance still to be recovered (no approved payroll took it) can be cancelled."""
    with transaction.atomic():
        advance = Advance.objects.select_for_update().filter(pk=advance_id).first()
        if advance is None:
            raise NotFound(_("Not found."))
        employee = get_employee(advance.employee_id, actor, ADVANCE_MANAGE)
        if actor is not None:
            actor.require(ADVANCE_MANAGE, branch=employee.branch_id)
        if advance.status != AdvanceStatus.OPEN:
            raise Conflict(_("Only an advance still to be recovered can be cancelled."),
                           code="LOANS_ADVANCE_STATE")
        advance.status = AdvanceStatus.CANCELLED
        advance.updated_by = getattr(actor, "user", None)
        advance.save(update_fields=["status", "updated_by", "updated_at"])
        return advance
