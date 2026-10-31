"""Lines added to a payslip by hand, while its run is a draft."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, invalid_fields

from ..models import ManualLine, Payslip
from ..permissions import CALCULATE
from .runs import gatherer_for, locked_run, require_draft, save_payslip, totals


@dataclass(frozen=True)
class ManualLineInput:
    employee_id: int
    label: str
    amount: Decimal
    addition: bool = True
    taxable: bool = True


def add_manual_line(run_id: int, data: ManualLineInput, *, actor=None) -> Payslip:
    with transaction.atomic():
        run = locked_run(run_id, actor, CALCULATE)
        require_draft(run)
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
        slip = save_payslip(run, employee.employee, gatherer_for(run))
        totals(run)
        run.save()
        return slip


def remove_manual_line(line_id: int, *, actor=None) -> Payslip:
    with transaction.atomic():
        line = ManualLine.objects.filter(pk=line_id).first()
        if line is None:
            raise NotFound(_("Not found."))
        run = locked_run(line.run_id, actor, CALCULATE)
        require_draft(run)
        employee = line.employee
        line.delete()
        slip = save_payslip(run, employee, gatherer_for(run))
        totals(run)
        run.save()
        return slip
