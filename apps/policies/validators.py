"""The rules on lateness and overtime bands."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _lazy

from apps.core.errors import invalid_fields

from .domain.bands import Band, band_problems

BAND_MESSAGES = {
    "reversed": _lazy("'To' must not be less than 'from'."),
    "negative": _lazy("Hours must not be negative."),
    "overlap": _lazy("This band overlaps another one."),
}


def check_bands(bands: list[Band]) -> None:
    problems = band_problems(bands)
    if problems:
        raise invalid_fields(
            {"bands": {str(i): [str(BAND_MESSAGES[p])] for i, p in problems.items()}})
