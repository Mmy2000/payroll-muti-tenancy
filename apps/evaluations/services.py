"""Evaluations: writing them, and the facts their card shows (PayRole Eva/views.py
`employee_year_data`).

The card's pay is this system's, not the card's current numbers: the yearly base is the pay in
effect at the year's end × 12 months (PayRole: the current salary × 12, whatever the year), and
the year's allowances are what the approved payslips of the year added and took through pay
items (PayRole summed the items as entered, paid or not).

Permissions: `evaluations.evaluation.view` / `.manage`, by the employee's branch; the pay facts
need `employees.salary.read` too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, ValidationError
from apps.core.history import in_effect
from apps.employees.services import SALARY_READ, get_employee, visible_employees

from .models import Evaluation

VIEW, MANAGE = "evaluations.evaluation.view", "evaluations.evaluation.manage"
ZERO = Decimal(0)


def visible(actor):
    rows = Evaluation.objects.select_related("employee__branch", "employee__department")
    if actor is None:
        return rows
    return rows.filter(employee__in=visible_employees(actor, VIEW))


def next_number() -> int:
    return (Evaluation.objects.aggregate(top=Max("number"))["top"] or 0) + 1


@dataclass(frozen=True)
class EvaluationInput:
    employee_id: int
    year: int
    evaluated_on: date
    note_1: str = ""
    note_2: str = ""
    note_3: str = ""
    note_4: str = ""


def save(data: EvaluationInput, *, evaluation_id: int | None = None,
         actor=None) -> Evaluation:
    notes = [n.strip() for n in (data.note_1, data.note_2, data.note_3, data.note_4)]
    errors = {}
    if not 2000 <= data.year <= 2100:
        errors["year"] = [_("Enter the year evaluated.")]
    if not any(notes):
        errors["note_1"] = [_("Write at least one note.")]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    with transaction.atomic():
        employee = get_employee(data.employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        if evaluation_id is None:
            row = Evaluation(number=next_number(), created_by=getattr(actor, "user", None))
        else:
            row = visible(actor).select_for_update(of=("self",)).filter(pk=evaluation_id).first()
            if row is None:
                raise NotFound(_("Not found."))
        row.employee, row.year, row.evaluated_on = employee, data.year, data.evaluated_on
        row.note_1, row.note_2, row.note_3, row.note_4 = notes
        row.updated_by = getattr(actor, "user", None)
        try:
            with transaction.atomic():
                row.save()
        except IntegrityError:  # two at the same moment took the same number
            row.number = next_number()
            row.save()
    return row


def delete(evaluation_id: int, *, actor=None) -> None:
    with transaction.atomic():
        row = visible(actor).filter(pk=evaluation_id).first()
        if row is None:
            raise NotFound(_("Not found."))
        if actor is not None:
            actor.require(MANAGE, branch=row.employee.branch_id)
        row.delete()


def card(evaluation: Evaluation, actor=None) -> dict:
    """What the card shows: the employee's dates, and their pay for the year when the reader
    may see pay."""
    from apps.payroll.models import PayslipLine, RunStatus

    person = evaluation.employee
    facts = {"birth_date": person.birth_date, "hired_on": person.hired_on,
             "insured_from": person.insured_from, "pay": None}
    if actor is not None and not actor.can(SALARY_READ, branch=person.branch_id):
        return facts
    history = person.pay_history.all()
    first = history.order_by("effective_from", "id").first()
    year_end = min(date(evaluation.year, 12, 31), person.left_on or date.max)
    current = in_effect(history, year_end) or first
    if current is None:
        return facts
    lines = PayslipLine.objects.filter(
        payslip__employee=person, code="item",
        payslip__run__status__in=(RunStatus.APPROVED, RunStatus.PAID),
        payslip__run__period__end__year=evaluation.year)
    items = lines.aggregate(
        added=Sum("amount", filter=Q(kind="earning")),
        taken=Sum("amount", filter=Q(kind="deduction")))
    base = current.terms.monthly * 12
    allowances = (items["added"] or ZERO) - (items["taken"] or ZERO)
    facts["pay"] = {"starting_salary": first.salary if first else None,
                    "insured_salary": current.insured_salary, "yearly_base": base,
                    "allowances": allowances, "total": base + allowances,
                    "daily": current.terms.daily}
    return facts
