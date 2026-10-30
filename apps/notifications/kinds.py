"""How each kind of notification looks. A new kind is one line here (and in models.Kind)."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Kind


@dataclass(frozen=True)
class Look:
    icon: str
    tone: str  # neutral, positive, negative, action, money (.notice-icon in app.css)


LOOKS = {
    Kind.LEAVE_REQUEST: Look("calendar-days", "action"),
    Kind.LEAVE_WITHDRAWN: Look("calendar-x", "neutral"),
    Kind.LEAVE_ADDED: Look("calendar-days", "neutral"),
    Kind.LEAVE_APPROVED: Look("calendar-check", "positive"),
    Kind.LEAVE_REJECTED: Look("calendar-x", "negative"),
    Kind.LEAVE_CANCELLED: Look("calendar-x", "negative"),
    Kind.PERMISSION_ADDED: Look("calendar-clock", "neutral"),
    Kind.PERMISSION_CANCELLED: Look("calendar-clock", "negative"),
    Kind.MOVEMENT: Look("hand-coins", "money"),
    Kind.SALARY_PAID: Look("banknote", "positive"),
}
DEFAULT = Look("bell", "neutral")
ICONS = sorted({DEFAULT.icon, *(look.icon for look in LOOKS.values())})


def look(kind: str) -> Look:
    return LOOKS.get(kind, DEFAULT)
