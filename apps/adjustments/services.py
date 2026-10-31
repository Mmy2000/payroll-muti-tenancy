"""Incentives and penalties: their types, and batches given to an employee, a department or a
branch, through their life:

    draft ──approve──▶ approved ──reopen (reason, not paid)──▶ draft
      │                   ├──cancel (reason, not paid)──▶ cancelled
      └─delete            └──correct (reason)──▶ a new correction batch (draft or approved)

A draft is edited freely (its details, who is in it, each row's quantity) and is never paid.
Once approved, nothing is overwritten silently: while no approved payroll has paid it, it may be
reopened or cancelled with a reason; after that, only a correction pays or takes back the
difference, in a later payroll. Every change bumps the batch's `revision` with its reason, so the
audit trail has who, when, what and why.

The kind decides the permission (`adjustments.incentive.*` or `adjustments.penalty.*`):
`manage` gives and edits drafts, `approve` approves, reopens, cancels and corrects. The amount is
worked out from the pay in effect on the row's date (apps.adjustments.domain.amounts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.errors import Conflict, DomainError, NotFound, ValidationError, invalid_fields
from apps.core.events import publish
from apps.core.history import in_effect
from apps.employees.selectors import visible_employees
from apps.employees.targets import Target, resolve

from .domain.amounts import METHODS
from .events import BatchApproved
from .models import Adjustment, AdjustmentBatch, AdjustmentKind, AdjustmentType, BatchStatus
from .permissions import permission
from .selectors import ZERO, effective_amounts, paid_rows

# --- types ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeInput:
    kind: str
    code: int
    name: str


def save_type(data: TypeInput, *, type_id: int | None = None, actor=None) -> AdjustmentType:
    if data.kind not in AdjustmentKind.values:
        raise invalid_fields({"kind": [_("Choose incentive or penalty.")]})
    if actor is not None:
        actor.require(permission(data.kind, "manage"))
    name = data.name.strip()
    with transaction.atomic():
        found = AdjustmentType() if type_id is None else AdjustmentType.objects.filter(
            pk=type_id).select_for_update().first()
        if found is None:
            raise NotFound(_("Not found."))
        if found.pk and found.kind != data.kind:
            raise invalid_fields({"kind": [_("A type can't change kind.")]})
        others = AdjustmentType.objects.filter(kind=data.kind).exclude(pk=found.pk)
        errors = {}
        if not name:
            errors["name"] = [_("Enter a name.")]
        elif others.filter(name=name).exists():
            errors["name"] = [_("Another type has this name.")]
        if others.filter(code=data.code).exists():
            errors["code"] = [_("Another type has this code.")]
        if errors:
            raise invalid_fields(errors)
        found.kind, found.code, found.name = data.kind, data.code, name
        found.updated_by = getattr(actor, "user", None)
        found.save()
    return found


def set_type_active(type_id: int, active: bool, *, actor=None) -> AdjustmentType:
    found = AdjustmentType.objects.filter(pk=type_id).first()
    if found is None:
        raise NotFound(_("Not found."))
    if actor is not None:
        actor.require(permission(found.kind, "manage"))
    found.is_active = active
    found.save(update_fields=["is_active", "updated_at"])
    return found


def seed_types(**_values) -> None:
    """A new client's starting list (apps.core.seeding), in the client's language."""
    if AdjustmentType.objects.exists():
        return
    rows = [(AdjustmentKind.INCENTIVE, 1, _("Performance bonus")),
            (AdjustmentKind.INCENTIVE, 2, _("Attendance bonus")),
            (AdjustmentKind.PENALTY, 1, _("Lateness")),
            (AdjustmentKind.PENALTY, 2, _("Unexcused absence")),
            (AdjustmentKind.PENALTY, 3, _("Breaking the rules"))]
    for kind, code, name in rows:
        AdjustmentType.objects.create(kind=kind, code=code, name=name)


# --- reading -------------------------------------------------------------------------------


# --- the details of a batch ------------------------------------------------------------------


@dataclass(frozen=True)
class AdjustmentInput:
    type_id: int
    target: Target
    date: date
    method: str
    quantity: Decimal
    reason: str = ""


@dataclass(frozen=True)
class BatchInput:
    """A draft's details: changing them works every row out again."""

    type_id: int
    date: date
    method: str
    quantity: Decimal
    reason: str = ""


def _checked(type_id: int, method_key: str, quantity: Decimal, *, kind: str | None = None):
    found = AdjustmentType.objects.filter(pk=type_id, is_active=True).first()
    errors = {}
    if found is None or (kind is not None and found.kind != kind):
        errors["type_id"] = [_("Choose an active type.")]
    method = METHODS.get(method_key)
    if method is None:
        errors["method"] = [_("Choose how the amount is counted.")]
    if quantity <= 0:
        errors["quantity"] = [_("Must be greater than zero.")]
    if errors:
        raise invalid_fields(errors)
    return found, method


def _amount(employee, method, quantity: Decimal, day: date) -> Decimal:
    pay = in_effect(employee.pay_history.all(), day)
    if pay is None:
        raise invalid_fields({"date": [_("%(name)s has no pay on that day.")
                                       % {"name": employee.name}]})
    return method.amount(quantity, pay.terms)


def _row(batch: AdjustmentBatch, employee, method, quantity: Decimal, actor) -> Adjustment:
    locks.ensure_open(employee.pk, batch.date)
    return Adjustment(batch=batch, employee=employee, adjustment_type=batch.adjustment_type,
                      kind=batch.kind, date=batch.date, method=method.key, quantity=quantity,
                      amount=_amount(employee, method, quantity, batch.date),
                      reason=batch.reason, created_by=getattr(actor, "user", None))


def _locked(batch_id: int, actor, action: str) -> AdjustmentBatch:
    """The batch, locked, if the actor may `action` it: the kind's permission, and every one of
    its employees in their branches."""
    batch = AdjustmentBatch.objects.select_for_update().filter(pk=batch_id).first()
    if batch is None:
        raise NotFound(_("Not found."))
    if actor is not None:
        code = permission(batch.kind, action)
        actor.require(code)
        if batch.rows.exclude(employee__in=visible_employees(actor, code)).exists():
            raise NotFound(_("Not found."))
    return batch


def _require(batch: AdjustmentBatch, *statuses: str) -> None:
    if batch.status not in statuses:
        raise Conflict(_("This batch is %(status)s.")
                       % {"status": batch.get_status_display().lower()},
                       code="ADJUSTMENTS_STATE")


def _require_editable(batch: AdjustmentBatch) -> None:
    _require(batch, BatchStatus.DRAFT)
    if batch.corrects_id is not None:
        raise DomainError(_("A correction is worked out from its batch: delete it and correct "
                            "again."), code="ADJUSTMENTS_CORRECTION")


def _touch(batch: AdjustmentBatch, reason: str, actor, *fields: str) -> None:
    """Record a change: one more revision, its reason, who made it (the audit trail keeps
    each)."""
    batch.revision += 1
    batch.change_reason = reason.strip()
    batch.updated_by = getattr(actor, "user", None)
    batch.save(update_fields=["revision", "change_reason", "updated_by", "updated_at", *fields])


def _need_reason(reason: str) -> None:
    if not reason.strip():
        raise invalid_fields({"reason": [_("Say why.")]})


def _ensure_unpaid(batch: AdjustmentBatch) -> None:
    if paid_rows(batch):
        raise DomainError(_("An approved payroll already paid this batch: correct it instead, "
                            "and the difference is settled in the next payroll."),
                          code="ADJUSTMENTS_PAID")


# --- giving and drafts -----------------------------------------------------------------------


def give(data: AdjustmentInput, *, approve: bool = False, actor=None) -> AdjustmentBatch:
    """A batch with one row per employee the target means on the day: a draft, or approved at
    once (with the approve permission)."""
    found, method = _checked(data.type_id, data.method, data.quantity)
    manage = permission(found.kind, "manage")
    if actor is not None:
        actor.require(manage)
        if approve:
            actor.require(permission(found.kind, "approve"))
    with transaction.atomic():
        batch = AdjustmentBatch.objects.create(
            kind=found.kind, adjustment_type=found, date=data.date, method=method.key,
            quantity=data.quantity, reason=data.reason.strip(), target_kind=data.target.kind,
            target_id=data.target.id, created_by=getattr(actor, "user", None))
        people = resolve(data.target, on=data.date, actor=actor, permission=manage)
        Adjustment.objects.bulk_create([_row(batch, e, method, data.quantity, actor)
                                        for e in people])
        if approve:
            _approve(batch, actor)
    return batch


def update_draft(batch_id: int, data: BatchInput, *, reason: str = "",
                 actor=None) -> AdjustmentBatch:
    """New details for a draft; every row takes the new quantity, worked out again."""
    with transaction.atomic():
        batch = _locked(batch_id, actor, "manage")
        _require_editable(batch)
        found, method = _checked(data.type_id, data.method, data.quantity, kind=batch.kind)
        batch.adjustment_type, batch.date, batch.method = found, data.date, method.key
        batch.quantity, batch.reason = data.quantity, data.reason.strip()
        _touch(batch, reason, actor, "adjustment_type", "date", "method", "quantity", "reason")
        for row in batch.rows.select_related("employee"):
            locks.ensure_open(row.employee_id, batch.date)
            row.adjustment_type, row.date, row.method = found, batch.date, method.key
            row.quantity, row.reason = data.quantity, batch.reason
            row.amount = _amount(row.employee, method, data.quantity, batch.date)
            row.updated_by = getattr(actor, "user", None)
            row.save()
    return batch


def add_to_draft(batch_id: int, target: Target, *, reason: str = "",
                 actor=None) -> list[Adjustment]:
    """More employees in a draft (an employee, a department or a branch); those already in it
    are left as they are."""
    with transaction.atomic():
        batch = _locked(batch_id, actor, "manage")
        _require_editable(batch)
        method = METHODS[batch.method]
        present = set(batch.rows.values_list("employee_id", flat=True))
        people = [e for e in resolve(target, on=batch.date, actor=actor,
                                     permission=permission(batch.kind, "manage"))
                  if e.pk not in present]
        if not people:
            message = _("They are all in this batch already.")
            raise ValidationError(message, fields={"target_id": [message]})
        made = Adjustment.objects.bulk_create([_row(batch, e, method, batch.quantity, actor)
                                               for e in people])
        _touch(batch, reason, actor)
    return made


def _locked_row(row_id: int, actor) -> tuple[AdjustmentBatch, Adjustment]:
    batch_id = Adjustment.objects.filter(pk=row_id).values_list("batch_id", flat=True).first()
    if batch_id is None:
        raise NotFound(_("Not found."))
    batch = _locked(batch_id, actor, "manage")
    _require_editable(batch)
    return batch, batch.rows.select_related("employee").get(pk=row_id)


def set_row_quantity(row_id: int, quantity: Decimal, *, reason: str = "",
                     actor=None) -> Adjustment:
    """One employee's quantity in a draft (the others keep the batch's)."""
    if quantity <= 0:
        raise invalid_fields({"quantity": [_("Must be greater than zero.")]})
    with transaction.atomic():
        batch, row = _locked_row(row_id, actor)
        row.quantity = quantity
        row.amount = _amount(row.employee, METHODS[row.method], quantity, row.date)
        row.updated_by = getattr(actor, "user", None)
        row.save(update_fields=["quantity", "amount", "updated_by", "updated_at"])
        _touch(batch, reason, actor)
    return row


def remove_row(row_id: int, *, reason: str = "", actor=None) -> None:
    with transaction.atomic():
        batch, row = _locked_row(row_id, actor)
        if batch.rows.count() == 1:
            raise DomainError(_("This is the batch's only employee: delete the draft instead."),
                              code="ADJUSTMENTS_LAST_ROW")
        row.delete()
        _touch(batch, reason, actor)


def delete_draft(batch_id: int, *, actor=None) -> None:
    with transaction.atomic():
        batch = _locked(batch_id, actor, "manage")
        _require(batch, BatchStatus.DRAFT)
        batch.delete()


# --- approval, and changing an approved batch ----------------------------------------------


def _approve(batch: AdjustmentBatch, actor) -> None:
    for employee_id in batch.rows.values_list("employee_id", flat=True):
        locks.ensure_open(employee_id, batch.date)
    batch.status, batch.approved_at = BatchStatus.APPROVED, timezone.now()
    batch.approved_by = getattr(actor, "user", None)
    _touch(batch, "", actor, "status", "approved_at", "approved_by")
    publish(BatchApproved(batch=batch, by=actor))


def approve(batch_id: int, *, actor=None) -> AdjustmentBatch:
    with transaction.atomic():
        batch = _locked(batch_id, actor, "approve")
        _require(batch, BatchStatus.DRAFT)
        if not batch.rows.exists():
            raise DomainError(_("Nobody is in this batch."), code="ADJUSTMENTS_EMPTY")
        _approve(batch, actor)
    return batch


def reopen(batch_id: int, reason: str, *, actor=None) -> AdjustmentBatch:
    """Back to a draft, to be edited and approved again; refused once paid."""
    _need_reason(reason)
    with transaction.atomic():
        batch = _locked(batch_id, actor, "approve")
        _require(batch, BatchStatus.APPROVED)
        _ensure_unpaid(batch)
        if batch.corrections.exclude(status=BatchStatus.CANCELLED).exists():
            raise DomainError(_("This batch has corrections: correct it again instead."),
                              code="ADJUSTMENTS_CORRECTED")
        batch.status, batch.approved_at, batch.approved_by = BatchStatus.DRAFT, None, None
        _touch(batch, reason, actor, "status", "approved_at", "approved_by")
    return batch


def cancel(batch_id: int, reason: str, *, actor=None) -> AdjustmentBatch:
    """Take back an approved batch no payroll has paid; it stays on record, cancelled."""
    _need_reason(reason)
    with transaction.atomic():
        batch = _locked(batch_id, actor, "approve")
        _require(batch, BatchStatus.APPROVED)
        _ensure_unpaid(batch)
        if batch.corrections.exclude(status=BatchStatus.CANCELLED).exists():
            raise DomainError(_("This batch has corrections: correct it again instead."),
                              code="ADJUSTMENTS_CORRECTED")
        batch.status = BatchStatus.CANCELLED
        _touch(batch, reason, actor, "status")
    return batch


@dataclass(frozen=True)
class CorrectionInput:
    date: date  # the day the difference counts (an open payroll period)
    reason: str
    quantities: dict[int, Decimal]  # {row id: what it should have been; 0 takes it back}


def correct(batch_id: int, data: CorrectionInput, *, approve: bool = False,
            actor=None) -> AdjustmentBatch:
    """A correction batch for an approved one: for each row whose quantity should have been
    different, the difference between what it should pay and what it pays now (with earlier
    approved corrections). The original rows are never changed."""
    _need_reason(data.reason)
    with transaction.atomic():
        batch = _locked(batch_id, actor, "approve")
        _require(batch, BatchStatus.APPROVED)
        if batch.corrects_id is not None:
            raise DomainError(_("Correct the original batch, not a correction."),
                              code="ADJUSTMENTS_CORRECTION")
        if batch.corrections.filter(status=BatchStatus.DRAFT).exists():
            raise Conflict(_("A correction of this batch is still a draft: approve or delete "
                             "it first."), code="ADJUSTMENTS_DRAFT_CORRECTION")
        rows = {row.pk: row for row in batch.rows.select_related("employee")}
        errors = {f"quantities.{pk}": [_("Not a row of this batch.")]
                  for pk in data.quantities if pk not in rows}
        errors.update({f"quantities.{pk}": [_("Must not be negative.")]
                       for pk, quantity in data.quantities.items() if quantity < 0})
        if errors:
            raise invalid_fields(errors)
        method, now = METHODS[batch.method], effective_amounts(batch)
        changes = []
        for pk, quantity in data.quantities.items():
            row = rows[pk]
            should = _amount(row.employee, method, quantity, row.date) if quantity else ZERO
            if should != now[pk]:
                changes.append((row, quantity, should - now[pk]))
        if not changes:
            raise invalid_fields({"quantities": [_("Nothing changes.")]})
        fix = AdjustmentBatch.objects.create(
            kind=batch.kind, adjustment_type=batch.adjustment_type, date=data.date,
            method=batch.method, quantity=ZERO, reason=data.reason.strip(), corrects=batch,
            change_reason=data.reason.strip(), created_by=getattr(actor, "user", None))
        for row, quantity, difference in changes:
            locks.ensure_open(row.employee_id, data.date)
            Adjustment.objects.create(
                batch=fix, employee=row.employee, adjustment_type=batch.adjustment_type,
                kind=batch.kind, date=data.date, method=batch.method, quantity=quantity,
                amount=difference, reason=data.reason.strip(), corrects=row,
                created_by=getattr(actor, "user", None))
        if approve:
            _approve(fix, actor)
    return fix
