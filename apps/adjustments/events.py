"""What happens to incentives and penalties, for whoever cares (apps/core/events.py)."""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.events import Event


@dataclass(frozen=True)
class BatchApproved(Event):
    batch: object = None
