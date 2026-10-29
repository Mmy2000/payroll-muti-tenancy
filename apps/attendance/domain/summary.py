"""Totals over a list of days (an employee's month). Pure: no database."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .days import DayResult, Status


@dataclass(frozen=True)
class Summary:
    counts: Counter = field(default_factory=Counter)  # Status → days
    worked_minutes: int = 0
    late_minutes: int = 0
    early_minutes: int = 0
    extra_minutes: int = 0
    hourly_minutes: int = 0
    missing_check_outs: int = 0
    worked_rest_days: int = 0

    def days(self, status: Status) -> int:
        return self.counts.get(status, 0)


def summarize(results: Iterable[DayResult]) -> Summary:
    counts: Counter = Counter()
    totals = Counter()
    for day in results:
        counts[day.status] += 1
        totals["worked"] += day.worked_minutes
        totals["late"] += day.late_minutes
        totals["early"] += day.early_minutes
        totals["extra"] += day.extra_minutes
        totals["hourly"] += day.hourly_minutes
        totals["missing"] += day.missing_check_out
        totals["rest"] += day.status == Status.PRESENT and day.rest_day
    return Summary(counts, totals["worked"], totals["late"], totals["early"], totals["extra"],
                   totals["hourly"], totals["missing"], totals["rest"])
