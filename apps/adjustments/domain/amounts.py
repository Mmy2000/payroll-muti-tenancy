"""How an incentive or penalty is counted (Strategy). Pure: no database.

PayRole (Pun/batch_entry.py) offered four ways, chosen per entry: a fixed amount, a percentage
of the salary, days of pay or hours of pay. Each is a `Method` here; adding a way means adding a
class to `METHODS`, nothing else.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.core.numeric import round_money
from apps.employees.domain.rates import PayTerms

HUNDRED = Decimal(100)


class Method:
    key: str = ""
    label = ""
    unit = ""  # what the quantity is in, for the form

    def amount(self, quantity: Decimal, pay: PayTerms) -> Decimal:
        raise NotImplementedError


class Fixed(Method):
    key, label, unit = "fixed", _("Fixed amount"), _("amount")

    def amount(self, quantity, pay):
        return round_money(quantity)


class PercentOfSalary(Method):
    """A share of the salary as entered: the period's fixed salary, or the day's or hour's
    wage (PayRole: Enp/salary_base.py percent_of_salary)."""

    key, label, unit = "percent", _("Percentage of salary"), _("%")

    def amount(self, quantity, pay):
        return round_money(pay.salary * quantity / HUNDRED)


class DaysOfPay(Method):
    key, label, unit = "days", _("Days of pay"), _("days")

    def amount(self, quantity, pay):
        return round_money(pay.daily * quantity)


class HoursOfPay(Method):
    key, label, unit = "hours", _("Hours of pay"), _("hours")

    def amount(self, quantity, pay):
        return round_money(pay.hourly * quantity)


METHODS: dict[str, Method] = {m.key: m for m in (Fixed(), PercentOfSalary(), DaysOfPay(),
                                                 HoursOfPay())}
CHOICES = [(m.key, m.label) for m in METHODS.values()]
