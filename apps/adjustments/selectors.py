"""Reading batches for the screens and the API."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum

from apps.core import locks
from apps.employees.models import Employee
from apps.employees.selectors import visible_employees
from apps.org.models import Branch

from .models import Adjustment, AdjustmentBatch, AdjustmentType, BatchStatus
from .permissions import permission

SOURCE = "adjustments.Adjustment"  # what payroll records as paid (apps/core/locks.py)
ZERO = Decimal(0)


def types_of(kind: str):
    return AdjustmentType.objects.filter(kind=kind)


def active_types(kind: str):
    return types_of(kind).filter(is_active=True)


def type_choices(kind: str) -> list[tuple[int, str]]:
    return list(types_of(kind).values_list("pk", "name"))


def is_type_of(type_id: int, kind: str) -> bool:
    return types_of(kind).filter(pk=type_id).exists()


def branch_names() -> dict[int, str]:
    return dict(Branch.objects.values_list("pk", "name"))


def rows_of(kind: str):
    return Adjustment.objects.filter(kind=kind)


def for_employee(queryset, employee_id):
    return queryset.filter(rows__employee_id=employee_id)


def visible_batches(actor, kind: str):
    """The kind's batches whose every employee the actor may see (all of them for a member of
    every branch). A batch half in another branch is the other branch's managers' business."""
    batches = AdjustmentBatch.objects.filter(kind=kind)
    if actor is None or actor.branch_ids(permission(kind, "view")) is None:
        return batches
    hidden = Employee.objects.exclude(pk__in=visible_employees(actor, permission(kind, "view")))
    return batches.exclude(rows__employee__in=hidden)


def batches_in_status(actor, kind: str, status: str | None):
    """The API's list: every visible batch, or those in `status`, newest first."""
    batches = visible_batches(actor, kind).select_related("adjustment_type")
    batches = batches.filter(status=status) if status else batches
    return batches.order_by("-date", "-id")


def batches_with_totals(matching):
    """`people` and `total` on each of `matching`, newest first. Filter first, count after: a
    search through the rows must not count a row twice."""
    return (AdjustmentBatch.objects.filter(pk__in=matching.values("pk"))
            .select_related("adjustment_type")
            .annotate(people=Count("rows"), total=Sum("rows__amount"))
            .order_by("-date", "-id"))


def batch_for_page(actor, kind: str, pk: int) -> AdjustmentBatch | None:
    return (visible_batches(actor, kind).select_related(
        "adjustment_type", "approved_by", "created_by", "updated_by", "corrects")
        .filter(pk=pk).first())


def batch_rows(batch: AdjustmentBatch):
    return batch.rows.select_related("employee", "corrects").order_by("employee__code")


def corrected_quantities(batch: AdjustmentBatch) -> dict[int, Decimal]:
    """{row id: its quantity in the last approved correction, which wins}."""
    return dict(Adjustment.objects.filter(
        corrects__batch=batch, batch__status=BatchStatus.APPROVED).order_by("id")
        .values_list("corrects_id", "quantity"))


def corrections_of(batch: AdjustmentBatch):
    return batch.corrections.select_related("adjustment_type").order_by("-id")


def has_live_correction(batch: AdjustmentBatch) -> bool:
    return batch.corrections.exclude(status=BatchStatus.CANCELLED).exists()


def has_draft_correction(batch: AdjustmentBatch) -> bool:
    return batch.corrections.filter(status=BatchStatus.DRAFT).exists()


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
