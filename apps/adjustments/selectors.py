"""Reading batches for the screens and the API."""

from __future__ import annotations

from apps.employees.models import Employee
from apps.employees.services import visible_employees

from .models import AdjustmentBatch
from .services import permission


def visible_batches(actor, kind: str):
    """The kind's batches whose every employee the actor may see (all of them for a member of
    every branch). A batch half in another branch is the other branch's managers' business."""
    batches = AdjustmentBatch.objects.filter(kind=kind)
    if actor is None or actor.branch_ids(permission(kind, "view")) is None:
        return batches
    hidden = Employee.objects.exclude(pk__in=visible_employees(actor, permission(kind, "view")))
    return batches.exclude(rows__employee__in=hidden)
