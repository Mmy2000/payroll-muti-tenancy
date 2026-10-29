"""Reading effective-dated values (apps.core.models.EffectiveDatedModel): which row holds on a
day, and the spans of a history. Payroll asks for a period, so it gets every row that applies
to some day of it, each with the days it covers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import QuerySet


def in_effect(queryset: QuerySet, day: date):
    """The row in effect on `day` (the latest one starting on or before it), or None."""
    return queryset.filter(effective_from__lte=day).order_by("-effective_from", "-id").first()


@dataclass(frozen=True)
class Span:
    row: object
    start: date
    end: date  # inclusive


def spans(queryset: QuerySet, start: date, end: date) -> list[Span]:
    """The rows covering `start`..`end` (inclusive), in order, each cut to the days it holds.
    Days before the first row are not covered (no span)."""
    first = in_effect(queryset, start)
    later = list(queryset.filter(effective_from__gt=start, effective_from__lte=end)
                 .order_by("effective_from", "id"))
    rows = ([first] if first is not None else []) + later
    result = []
    for index, row in enumerate(rows):
        span_start = max(row.effective_from, start)
        span_end = (rows[index + 1].effective_from - timedelta(days=1)
                    if index + 1 < len(rows) else end)
        if span_start <= span_end:
            result.append(Span(row, span_start, span_end))
    return result


class Timeline:
    """Effective-dated rows already loaded, to find the one in effect on many days without a
    query each: `Timeline(rows).on(day)`."""

    def __init__(self, rows):
        import bisect

        self._bisect = bisect.bisect_right
        self.rows = sorted(rows, key=lambda r: (r.effective_from, r.pk))
        self.starts = [r.effective_from for r in self.rows]

    def on(self, day: date):
        index = self._bisect(self.starts, day) - 1
        return self.rows[index] if index >= 0 else None
