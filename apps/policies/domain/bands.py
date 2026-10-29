"""Minute bands (lateness and overtime policies): checking a set of bands, and finding the band
a number of minutes falls in. Pure: no database."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Band:
    from_minutes: int
    to_minutes: int
    hours: Decimal  # hours deducted (lateness) or paid (overtime)


def band_problems(bands: Sequence[Band]) -> dict[int, str]:
    """{index of the band: what is wrong}. Bands may come in any order; they must not overlap."""
    problems: dict[int, str] = {}
    for index, band in enumerate(bands):
        if band.to_minutes < band.from_minutes:
            problems[index] = "reversed"
        elif band.hours < 0:
            problems[index] = "negative"
    ordered = sorted((b.from_minutes, b.to_minutes, i) for i, b in enumerate(bands))
    for (_start, end, _i), (next_start, _end, next_index) in zip(ordered, ordered[1:],
                                                                 strict=False):
        if next_start <= end:
            problems.setdefault(next_index, "overlap")
    return problems


def band_for(bands: Sequence[Band], minutes: int) -> Band | None:
    """The band holding `minutes` (from and to both included), or None."""
    return next((b for b in bands if b.from_minutes <= minutes <= b.to_minutes), None)
