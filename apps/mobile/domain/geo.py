"""Distance on the earth's surface."""

from __future__ import annotations

import math

EARTH_M = 6_371_000


def distance_m(lat1, lng1, lat2, lng2) -> float:
    """Haversine, as PayRole measured tracks."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))
