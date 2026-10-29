"""The life of a request (leave days, hourly leave): a small state machine.

    pending ──approve──▶ approved ──cancel──▶ cancelled
       │  └──reject───▶ rejected
       └─────cancel───▶ cancelled

`decide()` checks the move is allowed and stamps who decided and when. What must hold before a
request may be approved (the leave balance, the monthly hours) is the caller's check, passed in
as `before_approve`, so each kind of request keeps its own rules.
"""

from __future__ import annotations

from collections.abc import Callable

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import Conflict

from .models import RequestStatus

APPROVE, REJECT, CANCEL = "approve", "reject", "cancel"
MOVES: dict[str, tuple[frozenset[str], str]] = {
    APPROVE: (frozenset({RequestStatus.PENDING}), RequestStatus.APPROVED),
    REJECT: (frozenset({RequestStatus.PENDING}), RequestStatus.REJECTED),
    CANCEL: (frozenset({RequestStatus.PENDING, RequestStatus.APPROVED}), RequestStatus.CANCELLED),
}
# Statuses that hold days or hours (for overlaps and balances).
ACTIVE = (RequestStatus.PENDING, RequestStatus.APPROVED)


def can_move(request, move: str) -> bool:
    allowed_from, _target = MOVES[move]
    return request.status in allowed_from


def decide(request, move: str, *, actor=None, note: str = "",
           before_approve: Callable[[object], None] | None = None):
    """Apply `move` to a request already locked by the caller, and save it."""
    if move not in MOVES:
        raise Conflict(_("Unknown action."), code="ATTENDANCE_UNKNOWN_ACTION")
    if not can_move(request, move):
        raise Conflict(_("This request is %(status)s already.")
                       % {"status": request.get_status_display().lower()},
                       code="ATTENDANCE_REQUEST_STATE")
    if move == APPROVE and before_approve is not None:
        before_approve(request)
    request.status = MOVES[move][1]
    request.decided_by = getattr(actor, "user", None)
    request.decided_at = timezone.now()
    request.decision_note = note.strip()
    request.updated_by = request.decided_by
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_note",
                                "updated_by", "updated_at"])
    return request
