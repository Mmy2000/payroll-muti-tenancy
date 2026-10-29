"""Day, hour and month rates from an employee's pay terms. Pure: no database.

Two things are kept apart (docs/payroll-design.md §1): the **wage type** (how pay is counted: a
fixed salary, a daily wage, an hourly wage) and the **pay frequency** (how often it is run:
monthly, biweekly, weekly). `salary` is the amount of one unit of the wage type: the salary of one
pay period, the day's wage or the hour's wage.

A fixed salary's day is the salary over the calendar days of its period length: 30 for a month,
as PayRole (Enp/salary_base.py), 14 and 7 for biweekly and weekly. PayRole paid weekly salaries as
monthly ÷ 30, which was wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.core.numeric import RATE, quantize

FIXED, DAILY, HOURLY = "fixed", "daily", "hourly"
MONTHLY, BIWEEKLY, WEEKLY = "monthly", "biweekly", "weekly"
PERIOD_DAYS = {MONTHLY: Decimal(30), BIWEEKLY: Decimal(14), WEEKLY: Decimal(7)}
PERIODS_A_YEAR = {MONTHLY: 12, BIWEEKLY: 26, WEEKLY: 52}
MONTH_DAYS = PERIOD_DAYS[MONTHLY]


@dataclass(frozen=True)
class PayTerms:
    wage_type: str
    pay_frequency: str
    salary: Decimal
    hours_per_day: Decimal

    @classmethod
    def of(cls, pay) -> PayTerms:
        """From a Compensation row (or anything with the same fields)."""
        return cls(pay.wage_type, pay.pay_frequency, pay.salary, pay.hours_per_day)

    @property
    def daily(self) -> Decimal:
        if self.wage_type == DAILY:
            return self.salary
        if self.wage_type == HOURLY:
            return quantize(self.salary * self.hours_per_day, RATE)
        return quantize(self.salary / PERIOD_DAYS[self.pay_frequency], RATE)

    @property
    def hourly(self) -> Decimal:
        if self.wage_type == HOURLY:
            return self.salary
        return quantize(self.daily / self.hours_per_day, RATE)

    @property
    def monthly(self) -> Decimal:
        """A month's pay: the salary of a monthly fixed salary, else 30 days."""
        if self.wage_type == FIXED and self.pay_frequency == MONTHLY:
            return self.salary
        return quantize(self.daily * MONTH_DAYS, RATE)
