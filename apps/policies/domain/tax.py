"""Progressive income tax over yearly income. Pure: no database.

PayRole (Salary/payroll.py monthly_tax): yearly income = the month's taxable pay × 12, less the
yearly exemption; taxed bracket by bracket; the month's tax is the yearly tax ÷ 12.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from apps.core.numeric import ZERO, round_money

HUNDRED = Decimal(100)
MONTHS = Decimal(12)


@dataclass(frozen=True)
class Bracket:
    up_to: Decimal | None  # yearly income this bracket reaches; None = everything above
    rate: Decimal  # percent


def bracket_problems(brackets: Sequence[Bracket]) -> dict[int, str]:
    """{index: what is wrong}: bounds must rise, only the last may be open, rates 0–100."""
    problems: dict[int, str] = {}
    previous = ZERO
    for index, bracket in enumerate(brackets):
        last = index == len(brackets) - 1
        if not ZERO <= bracket.rate <= HUNDRED:
            problems[index] = "rate"
        elif bracket.up_to is None and not last:
            problems[index] = "open_not_last"
        elif bracket.up_to is not None and bracket.up_to <= previous:
            problems[index] = "not_rising"
        if bracket.up_to is not None:
            previous = max(previous, bracket.up_to)
    return problems


def yearly_tax(taxable_income: Decimal, brackets: Sequence[Bracket]) -> Decimal:
    """Tax on a yearly income already reduced by the exemption. Income above a closed last
    bracket is taxed at the last bracket's rate."""
    remaining = max(taxable_income, ZERO)
    lower = ZERO
    tax = ZERO
    for bracket in brackets:
        if remaining <= 0:
            break
        width = remaining if bracket.up_to is None else min(remaining, bracket.up_to - lower)
        tax += width * bracket.rate / HUNDRED
        remaining -= width
        lower = bracket.up_to if bracket.up_to is not None else lower
    if remaining > 0 and brackets:
        tax += remaining * brackets[-1].rate / HUNDRED
    return tax


def monthly_tax(monthly_taxable: Decimal, annual_exemption: Decimal,
                brackets: Sequence[Bracket]) -> Decimal:
    yearly = monthly_taxable * MONTHS - annual_exemption
    return round_money(yearly_tax(yearly, brackets) / MONTHS)
