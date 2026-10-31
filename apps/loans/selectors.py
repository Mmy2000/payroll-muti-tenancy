"""What an employee has already taken, and the advances and loans a member may see."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.employees.selectors import employee_rows

from .models import Advance, AdvanceStatus, Loan
from .permissions import ADVANCE_VIEW, VIEW


def month_advances(employee, day: date) -> Decimal:
    open_ones = Advance.objects.filter(employee=employee, date__year=day.year,
                                       date__month=day.month).exclude(
        status=AdvanceStatus.CANCELLED)
    return open_ones.aggregate(total=Sum("amount"))["total"] or Decimal(0)


def visible_advances(actor):
    return employee_rows(Advance.objects.all(), actor, ADVANCE_VIEW).order_by("-date", "-id")


def loans_with_installments():
    return Loan.objects.prefetch_related("installments")


def visible_loans(actor):
    return employee_rows(loans_with_installments(), actor, VIEW).order_by("-granted_on", "-id")


def visible_loan(actor, pk: int) -> Loan | None:
    return employee_rows(Loan.objects.all(), actor, VIEW).filter(pk=pk).first()


def installments_of(loan: Loan):
    return loan.installments.all()
