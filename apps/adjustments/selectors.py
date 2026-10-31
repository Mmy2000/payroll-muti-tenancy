"""Reading batches for the screens and the API."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.core import locks
from apps.employees.models import Employee
from apps.employees.selectors import visible_employees

from .models import Adjustment, AdjustmentBatch, BatchStatus
from .permissions import permission

SOURCE = "adjustments.Adjustment"  # what payroll records as paid (apps/core/locks.py)
ZERO = Decimal(0)


def visible_batches(actor, kind: str):
    """The kind's batches whose every employee the actor may see (all of them for a member of
    every branch). A batch half in another branch is the other branch's managers' business."""
    batches = AdjustmentBatch.objects.filter(kind=kind)
    if actor is None or actor.branch_ids(permission(kind, "view")) is None:
        return batches
    hidden = Employee.objects.exclude(pk__in=visible_employees(actor, permission(kind, "view")))
    return batches.exclude(rows__employee__in=hidden)


def paid_rows(batch: AdjustmentBatch) -> set[int]:
    """The rows of `batch` an approved payroll has paid."""
    return {pk for pk in batch.rows.values_list("pk", flat=True)
            if locks.source_locked(SOURCE, pk)}


def effective_amounts(batch: AdjustmentBatch) -> dict[int, Decimal]:
    """{row id: what it pays once its approved corrections are counted}."""
    corrected = dict(Adjustment.objects.filter(
        corrects__batch=batch, batch__status=BatchStatus.APPROVED)
        .values("corrects_id").annotate(total=Sum("amount")).values_list("corrects_id", "total"))
    return {row.pk: row.amount + corrected.get(row.pk, ZERO) for row in batch.rows.all()}
