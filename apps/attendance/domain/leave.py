"""Counting leave. Pure: no database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


def days_between(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def leave_days(start: date, end: date, is_working_day: Callable[[date], bool]) -> int:
    """Working days from `start` to `end` (both included): days off and holidays are free."""
    return sum(1 for day in days_between(start, end) if is_working_day(day))


def span_minutes(starts_at: time, ends_at: time) -> int:
    """Minutes from one time to the next; past midnight when the end is earlier."""
    start = datetime.combine(date.min, starts_at)
    end = datetime.combine(date.min, ends_at)
    if end <= start:
        end += timedelta(days=1)
    return int((end - start).total_seconds() // 60)


@dataclass(frozen=True)
class Balance:
    """A year of leave counted against the annual balance."""

    entitled: int
    taken: int  # approved
    requested: int  # still waiting

    @property
    def remaining(self) -> int:
        return self.entitled - self.taken

    def allows(self, days: int) -> bool:
        return days <= self.remaining
