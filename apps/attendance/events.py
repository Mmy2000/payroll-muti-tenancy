"""What happens in attendance, for whoever cares (apps/core/events.py)."""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.events import Event


@dataclass(frozen=True)
class LeaveRequested(Event):
    request: object = None


@dataclass(frozen=True)
class LeaveEnteredApproved(Event):
    request: object = None


@dataclass(frozen=True)
class LeaveDecided(Event):
    request: object = None
    move: str = ""  # approve, reject or cancel


@dataclass(frozen=True)
class HourlyLeaveEntered(Event):
    request: object = None


@dataclass(frozen=True)
class HourlyLeaveCancelled(Event):
    request: object = None
