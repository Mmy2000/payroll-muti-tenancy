"""Calendar months, as the date of their first day. Pure: no database."""

from __future__ import annotations

from datetime import date, timedelta


def first_day(day: date) -> date:
    return day.replace(day=1)


def last_day(day: date) -> date:
    return add_months(first_day(day), 1) - timedelta(days=1)


def add_months(month: date, count: int) -> date:
    """The first day of the month `count` months after `month`'s."""
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def months(first: date, count: int) -> list[date]:
    """`count` months from `first`'s, as their first days."""
    start = first_day(first)
    return [add_months(start, i) for i in range(count)]


def parse(text: str, default: date) -> date:
    """The first day of "YYYY-MM", or of `default`'s month."""
    try:
        year, month = (int(part) for part in text.split("-")[:2])
        return date(year, month, 1)
    except (ValueError, TypeError):
        return first_day(default)
