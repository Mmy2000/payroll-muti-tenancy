"""Periods of employment, from assignment rows already loaded."""

from __future__ import annotations

from datetime import date


def closed_periods(rows) -> list[tuple[date, date]]:
    """(first day, last day) of each past period, from rows in date order: a period starts at
    the first row after the last one closed, and a row's `ended_on` closes it."""
    periods, start = [], None
    for row in rows:
        start = start or row.effective_from
        if row.ended_on is not None:
            periods.append((start, row.ended_on))
            start = None
    return periods
