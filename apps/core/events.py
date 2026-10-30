"""Domain events: a service says what happened, and whoever cares reacts (Observer).

Attendance, loans, payroll… state facts (`publish(LeaveRequested(...))`) and know nothing about
who listens, so a new reaction means a new subscriber, not a change to the service. Each app
defines its own events in its `events.py`; subscribers register from their AppConfig.ready().

Handlers run at once, in the caller's transaction: a reaction that fails undoes the action, and
an action that rolls back leaves no reaction behind.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    """Something that happened. `by` is whoever did it (an Actor or a Membership), if anyone."""

    by: object = None


_handlers: dict[type[Event], list[Callable]] = defaultdict(list)


def subscribe(event_type: type[Event]):
    """@subscribe(LeaveRequested) on a function taking the event."""

    def register(handler: Callable) -> Callable:
        if handler not in _handlers[event_type]:
            _handlers[event_type].append(handler)
        return handler

    return register


def publish(event: Event) -> None:
    for handler in _handlers[type(event)]:
        handler(event)
