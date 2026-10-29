"""Server-drawn charts (components/column_chart.html, bar_chart.html): the geometry only, pure.

One series per chart (the title says what it is; no legend). Marks follow the dashboard's
specs: columns and bars at most 24px thick with a 4px rounded data end, square at the baseline,
a hairline solid grid at clean ticks (0, 1K, 2K…), and values written selectively (the latest
and the highest). Every mark has a hit target the size of its band for the hover tooltip
(static/core/js/bars.js), and the template adds a table of the same numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

MAX_THICKNESS = 24
RADIUS = 4


@dataclass(frozen=True)
class Point:
    label: str  # the axis label (short)
    value: Decimal | int | float
    title: str = ""  # the tooltip's heading (defaults to the label)
    shown: str = ""  # the value as text (defaults to compact())


def compact(value) -> str:
    """1,284 → "1.3K", 12,900 → "12.9K", 4,200,000 → "4.2M"; below 1,000 as it is."""
    number = float(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(number) >= limit:
            text = f"{number / limit:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return f"{number:,.0f}" if number == int(number) else f"{number:,.1f}"


def nice_ticks(top: float, count: int = 4, *, whole: bool = False) -> list[float]:
    """0 and clean steps (1, 2, 2.5, 5 × 10^k) up to at least `top`; `whole`: steps of at
    least 1 (counts of people have no fractions)."""
    if top <= 0:
        return [0, 1]
    raw = top / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(power * m for m in (1, 2, 2.5, 5, 10) if power * m >= raw)
    if whole:
        step = max(1, math.ceil(step))
    steps = math.ceil(top / step - 1e-9)
    return [step * i for i in range(steps + 1)]


def _rounded_top(x, y, width, base) -> str:
    r = min(RADIUS, width / 2, base - y)
    return (f"M{x:.2f},{base:.2f}V{y + r:.2f}Q{x:.2f},{y:.2f} {x + r:.2f},{y:.2f}"
            f"H{x + width - r:.2f}Q{x + width:.2f},{y:.2f} {x + width:.2f},{y + r:.2f}"
            f"V{base:.2f}Z")


def _rounded_end(x, y, length, thickness) -> str:
    r = min(RADIUS, thickness / 2, length)
    end = x + length
    return (f"M{x:.2f},{y:.2f}H{end - r:.2f}Q{end:.2f},{y:.2f} {end:.2f},{y + r:.2f}"
            f"V{y + thickness - r:.2f}Q{end:.2f},{y + thickness:.2f} {end - r:.2f},"
            f"{y + thickness:.2f}H{x:.2f}Z")


def _labelled(points) -> set[int]:
    """Which marks carry their value: the last one and the highest."""
    if not points:
        return set()
    values = [float(p.value) for p in points]
    return {len(points) - 1, max(range(len(points)), key=values.__getitem__)}


def columns(points: list[Point], *, width: int = 520, height: int = 200,
            whole: bool = False) -> dict:
    """Vertical columns over a band per point (time going left to right). Drawn at about the
    width it is shown, so its text stays its size."""
    left, top_pad, bottom = 40, 18, 22
    plot_w, plot_h = width - left - 4, height - top_pad - bottom
    ticks = nice_ticks(max((float(p.value) for p in points), default=0), whole=whole)
    top = ticks[-1] or 1
    base = top_pad + plot_h
    band = plot_w / max(len(points), 1)
    thickness = min(MAX_THICKNESS, band * 0.62)
    every = max(1, math.ceil(len(points) / 8))  # axis labels that fit
    labelled = _labelled(points)
    marks = []
    for i, point in enumerate(points):
        value = float(point.value)
        x = left + i * band + (band - thickness) / 2
        h = max(value, 0) / top * plot_h
        y = base - h
        marks.append({
            "path": _rounded_top(x, y, thickness, base) if h > 0 else "",
            "hit_x": round(left + i * band, 2), "hit_w": round(band, 2),
            "label_x": round(x + thickness / 2, 2),
            # An axis label near an edge leans inward instead of being cut.
            "axis_x": round(min(max(x + thickness / 2, left + 22), width - 2), 2),
            "axis_anchor": "end" if x + thickness / 2 > width - 30 else "middle",
            # Counted back from the latest, so it is always labelled and the gaps stay even.
            "axis_label": point.label if (len(points) - 1 - i) % every == 0 else "",
            "value_y": round(y - 5, 2), "shown": point.shown or compact(value),
            "show_value": i in labelled and value > 0,
            "title": point.title or point.label})
    return {"width": width, "height": height, "base": base, "left": left, "top": top_pad,
            "plot_h": plot_h,
            "right": width - 4, "axis_y": height - 6, "marks": marks,
            "ticks": [{"y": round(base - t / top * plot_h, 2), "text": compact(t)}
                      for t in ticks],
            "rows": [(p.title or p.label, p.shown or compact(p.value)) for p in points]}


def bars(points: list[Point], *, width: int = 520, row: int = 30) -> dict:
    """Horizontal bars, one row per point (categories), longest first."""
    points = sorted(points, key=lambda p: float(p.value), reverse=True)
    label_w, right_pad = 130, 56
    plot_w = width - label_w - right_pad
    ticks = nice_ticks(max((float(p.value) for p in points), default=0))
    top = ticks[-1] or 1
    thickness = min(MAX_THICKNESS, row * 0.62)
    height = row * len(points) + 8
    marks = []
    for i, point in enumerate(points):
        value = float(point.value)
        y = i * row + (row - thickness) / 2 + 4
        length = max(value, 0) / top * plot_w
        marks.append({
            "path": _rounded_end(label_w, y, length, thickness) if length > 0 else "",
            "hit_y": round(i * row + 4, 2), "hit_h": row, "text_y": round(y + thickness / 2, 2),
            "value_x": round(label_w + length + 6, 2), "label": point.label,
            "shown": point.shown or compact(value), "title": point.title or point.label})
    return {"width": width, "height": height, "start": label_w, "marks": marks,
            "ticks": [{"x": round(label_w + t / top * plot_w, 2)} for t in ticks],
            "rows": [(p.title or p.label, p.shown or compact(p.value)) for p in points]}
