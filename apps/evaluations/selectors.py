"""Evaluations: which ones an actor may see, and an evaluation as its printed card."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Max, Q, Sum

from apps.core.history import in_effect
from apps.employees.permissions import SALARY_READ
from apps.employees.selectors import visible_employees

from .models import Evaluation
from .permissions import VIEW

ZERO = Decimal(0)


def visible(actor):
    rows = Evaluation.objects.select_related("employee__branch", "employee__department")
    if actor is None:
        return rows
    return rows.filter(employee__in=visible_employees(actor, VIEW))


def next_number() -> int:
    return (Evaluation.objects.aggregate(top=Max("number"))["top"] or 0) + 1


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
