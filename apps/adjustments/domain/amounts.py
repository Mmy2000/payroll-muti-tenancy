"""How an incentive or penalty is counted (Strategy). Pure: no database.

PayRole (Pun/batch_entry.py) offered four ways, chosen per entry: a fixed amount, a percentage
of the salary, days of pay or hours of pay. Each is a `Method` here; adding a way means adding a
class to `METHODS`, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.core.numeric import round_money
from apps.employees.domain.rates import daily_rate, hourly_rate

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Pay:
    """The pay an amount is counted from (the employee's pay in effect that day)."""

    basis: str
    salary: Decimal
    hours_per_day: Decimal


class Method:
    key: str = ""
    label = ""
    unit = ""  # what the quantity is in, for the form

    def amount(self, quantity: Decimal, pay: Pay) -> Decimal:
        raise NotImplementedError


class Fixed(Method):
    key, label, unit = "fixed", _("Fixed amount"), _("amount")

    def amount(self, quantity, pay):
        return round_money(quantity)


class PercentOfSalary(Method):
    """A share of the salary as entered: the month's salary, the week's or the day's wage
    (PayRole: Enp/salary_base.py percent_of_salary)."""

    key, label, unit = "percent", _("Percentage of salary"), _("%")

    def amount(self, quantity, pay):
        return round_money(pay.salary * quantity / HUNDRED)


class DaysOfPay(Method):
    key, label, unit = "days", _("Days of pay"), _("days")

    def amount(self, quantity, pay):
        return round_money(daily_rate(pay.basis, pay.salary) * quantity)


class HoursOfPay(Method):
    key, label, unit = "hours", _("Hours of pay"), _("hours")

    def amount(self, quantity, pay):
        return round_money(hourly_rate(pay.basis, pay.salary, pay.hours_per_day) * quantity)


METHODS: dict[str, Method] = {m.key: m for m in (Fixed(), PercentOfSalary(), DaysOfPay(),
                                                 HoursOfPay())}
CHOICES = [(m.key, m.label) for m in METHODS.values()]
