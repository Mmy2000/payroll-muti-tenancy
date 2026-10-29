"""How much of a scheduled amount falls in a pay period (docs/payroll-design.md §4). Pure: no
database.

Every recurring amount is allocated by one rule, chosen by the item's frequency and the
employee's pay frequency:

* the same unit as the pay period (an item "every pay period"; a monthly item for a monthly
  employee; a weekly item for a weekly employee): the full amount each period, prorated by days
  when the item or the employment covers only part of it;
* a monthly item for a weekly or biweekly employee: **split by calendar days** (each period gets
  the days it covers of each month, so a month's shares add up to the amount exactly), or, if the
  client chose it, **whole in the period containing the 1st of the month**;
* a weekly item for a monthly or biweekly employee: the amount × days covered ÷ 7.

A one-time amount falls in the period containing its date.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from apps.core.months import add_months, first_day
from apps.core.numeric import ZERO, round_money

from .periods import Period

SPLIT, FIRST_RUN = "split", "first_run"  # how monthly amounts reach weekly/biweekly periods


@dataclass(frozen=True)
class Window:
    """The days something applies: the item's own range cut to the employment."""

    start: date
    end: date | None  # open

    def cut(self, period: Period) -> Period | None:
        start = max(self.start, period.start)
        end = period.end if self.end is None else min(self.end, period.end)
        return Period(start, end) if start <= end else None


def _days(period: Period | None) -> int:
    return period.days if period is not None else 0


def per_period(amount: Decimal, period: Period, window: Window) -> Decimal:
    covered = window.cut(period)
    if covered is None:
        return ZERO
    if covered == period:
        return round_money(amount)
    return round_money(amount * covered.days / period.days)


def by_week(amount: Decimal, period: Period, window: Window) -> Decimal:
    return round_money(amount * _days(window.cut(period)) / 7)


def _month_share(amount: Decimal, month: date, covered: Period) -> Decimal:
    """The month's amount for its days `covered`, as "allocated through the last covered day"
    minus "through the day before the first": consecutive periods' shares add up exactly."""
    month_days = calendar.monthrange(month.year, month.month)[1]

    def through(day_index: int) -> Decimal:
        return round_money(amount * day_index / month_days)

    return through(covered.end.day) - through(covered.start.day - 1)


def split_by_days(amount: Decimal, period: Period, window: Window) -> Decimal:
    covered = window.cut(period)
    if covered is None:
        return ZERO
    total = ZERO
    month = first_day(covered.start)
    while month <= covered.end:
        month_end = add_months(month, 1) - timedelta(days=1)
        part = Period(max(month, covered.start), min(month_end, covered.end))
        total += _month_share(amount, month, part)
        month = add_months(month, 1)
    return total


def whole_on_the_first(amount: Decimal, period: Period, window: Window) -> Decimal:
    """The whole amount in the period containing each month's 1st (when the item runs then)."""
    total = ZERO
    month = first_day(period.start)
    if month < period.start:
        month = add_months(month, 1)
    while month <= period.end:
        if window.start <= month and (window.end is None or month <= window.end):
            total += round_money(amount)
        month = add_months(month, 1)
    return total


Rule = Callable[[Decimal, Period, Window], Decimal]


def rule_for(item_frequency: str, pay_frequency: str, monthly_rule: str = SPLIT) -> Rule:
    """The allocation rule for a recurring item (frequency "period", "monthly" or "weekly")."""
    if item_frequency == "period" or item_frequency == pay_frequency:
        return per_period
    if item_frequency == "monthly":
        return whole_on_the_first if monthly_rule == FIRST_RUN else split_by_days
    if item_frequency == "weekly":
        return by_week
    raise ValueError(f"unknown item frequency {item_frequency!r}")


def once(amount: Decimal, day: date, period: Period, window: Window) -> Decimal:
    covered = window.cut(period)
    return round_money(amount) if covered is not None and covered.contains(day) else ZERO
