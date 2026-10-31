"""What an employee has already taken."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from .models import Advance, AdvanceStatus


def month_advances(employee, day: date) -> Decimal:
    open_ones = Advance.objects.filter(employee=employee, date__year=day.year,
                                       date__month=day.month).exclude(
        status=AdvanceStatus.CANCELLED)
    return open_ones.aggregate(total=Sum("amount"))["total"] or Decimal(0)
