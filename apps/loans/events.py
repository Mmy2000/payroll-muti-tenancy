"""What happens to advances and loans, for whoever cares (apps/core/events.py)."""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.events import Event


@dataclass(frozen=True)
class AdvanceGiven(Event):
    advance: object = None


@dataclass(frozen=True)
class LoanGranted(Event):
    loan: object = None
    installments: int = 0
