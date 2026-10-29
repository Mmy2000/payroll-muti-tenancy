"""Pay periods from a pay calendar (docs/payroll-design.md §2). Pure: no database.

A monthly calendar has a start day: 1 gives calendar months, 26 gives the 26th to the 25th. A
weekly or biweekly calendar has an anchor date, the first day of one of its periods; every other
period is a whole number of periods before or after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.core.months import add_months

LENGTH_DAYS = {"weekly": 7, "biweekly": 14}
MAX_START_DAY = 28  # every month has it


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def overlaps(self, other: Period) -> bool:
        return self.start <= other.end and other.start <= self.end


def monthly(day: date, start_day: int = 1) -> Period:
    """The monthly period containing `day`."""
    if not 1 <= start_day <= MAX_START_DAY:
        raise ValueError(f"start day {start_day} out of 1..{MAX_START_DAY}")
    first = date(day.year, day.month, start_day)
    if day < first:
        first = add_months(first, -1).replace(day=start_day)
    return Period(first, add_months(first, 1).replace(day=start_day) - timedelta(days=1))


def every(day: date, anchor: date, length_days: int) -> Period:
    """The fixed-length period (from `anchor`) containing `day`."""
    start = anchor + timedelta(days=(day - anchor).days // length_days * length_days)
    return Period(start, start + timedelta(days=length_days - 1))


def period_containing(day: date, frequency: str, *, start_day: int = 1,
                      anchor: date | None = None) -> Period:
    if frequency == "monthly":
        return monthly(day, start_day)
    if anchor is None:
        raise ValueError("a weekly or biweekly calendar needs an anchor date")
    return every(day, anchor, LENGTH_DAYS[frequency])


def following(period: Period, frequency: str, *, start_day: int = 1,
              anchor: date | None = None) -> Period:
    return period_containing(period.end + timedelta(days=1), frequency, start_day=start_day,
                             anchor=anchor)
