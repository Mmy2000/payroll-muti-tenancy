"""Daily and hourly rates from a salary. Pure: no database.

PayRole (Enp/salary_base.py): a month counts as 30 days for every monthly employee, whatever the
calendar says; a day's hours come from the employee. PayRole also treated weekly wages as
monthly ÷ 30, which is wrong. How weekly pay is counted is still to be decided (docs/PLAN.md,
"Open questions"), so until then a week is taken as 7 paid days.
"""

from __future__ import annotations

from decimal import Decimal

from apps.core.numeric import RATE, quantize

MONTH_DAYS = Decimal(30)
WEEK_DAYS = Decimal(7)


def daily_rate(basis: str, salary: Decimal) -> Decimal:
    if basis == "monthly":
        days = MONTH_DAYS
    elif basis == "weekly":
        days = WEEK_DAYS
    else:
        days = Decimal(1)
    return quantize(salary / days, RATE)


def hourly_rate(basis: str, salary: Decimal, hours_per_day: Decimal) -> Decimal:
    return quantize(daily_rate(basis, salary) / hours_per_day, RATE)


def monthly_pay(basis: str, salary: Decimal) -> Decimal:
    """A month's pay, whatever the basis: the salary, or 30 days of the daily rate."""
    return salary if basis == "monthly" else quantize(daily_rate(basis, salary) * MONTH_DAYS,
                                                       RATE)
