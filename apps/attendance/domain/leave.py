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


def minutes_of_day(starts_at: time, ends_at: time) -> tuple[int, int]:
    """A span as minutes from the start of its day: (start, end); the end is past 1440 when
    the span goes past midnight."""
    start = starts_at.hour * 60 + starts_at.minute
    return start, start + span_minutes(starts_at, ends_at)


def spans_overlap(a: tuple[time, time], b: tuple[time, time]) -> bool:
    """Two spans of the same day share a minute (touching ends don't: 10–11 and 11–12 are
    fine)."""
    (a_start, a_end), (b_start, b_end) = minutes_of_day(*a), minutes_of_day(*b)
    return a_start < b_end and b_start < a_end


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
