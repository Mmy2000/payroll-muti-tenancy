"""Pay items: the catalogue, and giving an item to employees on a schedule."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.employees.selectors import visible_employees
from apps.employees.targets import Target, resolve

from .models import (
    AssignmentStatus,
    ItemFrequency,
    PayItem,
    PayItemAssignment,
    PayItemBasis,
    PayItemKind,
)
from .permissions import GIVE
from .selectors import overlapping_assignments


@dataclass(frozen=True)
class PayItemInput:
    code: int
    name: str
    kind: str
    basis: str = PayItemBasis.FIXED
    taxable: bool = True


def save_pay_item(data: PayItemInput, *, item_id: int | None = None, actor=None) -> PayItem:
    if actor is not None:
        actor.require("compensation.item.manage")
    name = data.name.strip()
    errors = {}
    if not name:
        errors["name"] = [_("Enter a name.")]
    if data.kind not in PayItemKind.values:
        errors["kind"] = [_("Choose addition or deduction.")]
    if data.basis not in PayItemBasis.values:
        errors["basis"] = [_("Choose how the amount is counted.")]
    with transaction.atomic():
        if item_id is None:
            item = PayItem(created_by=getattr(actor, "user", None))
        else:
            item = PayItem.objects.select_for_update().filter(pk=item_id).first()
            if item is None:
                raise NotFound(_("Not found."))
        others = PayItem.objects.exclude(pk=item.pk)
        if others.filter(code=data.code).exists():
            errors["code"] = [_("Another item has this code.")]
        if name and others.filter(name=name).exists():
            errors["name"] = [_("Another item has this name.")]
        if errors:
            raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
        item.code, item.name, item.kind = data.code, name, data.kind
        item.basis, item.taxable = data.basis, data.taxable
        item.updated_by = getattr(actor, "user", None)
        item.save()
    return item


def set_pay_item_active(item_id: int, active: bool, *, actor=None) -> PayItem:
    if actor is not None:
        actor.require("compensation.item.manage")
    item = PayItem.objects.filter(pk=item_id).first()
    if item is None:
        raise NotFound(_("Not found."))
    item.is_active = active
    item.save(update_fields=["is_active", "updated_at"])
    return item


# --- giving items on a schedule -----------------------------------------------------------


@dataclass(frozen=True)
class AssignmentInput:
    item_id: int
    target: Target
    frequency: str
    amount: Decimal
    starts_on: date
    ends_on: date | None = None  # open-ended; a one-time item is on `starts_on` only
    note: str = ""


def give_items(data: AssignmentInput, *, actor=None) -> list[PayItemAssignment]:
    """The item for each employee the target means on `starts_on`, sharing a batch. An item
    already running for the employee over any of the same days is refused."""
    if actor is not None:
        actor.require(GIVE)
    item = PayItem.objects.filter(pk=data.item_id, is_active=True).first()
    ends_on = data.starts_on if data.frequency == ItemFrequency.ONCE else data.ends_on
    errors = {}
    if item is None:
        errors["item_id"] = [_("Choose an active pay item.")]
    if data.frequency not in ItemFrequency.values:
        errors["frequency"] = [_("Choose how often.")]
    if data.amount <= 0:
        errors["amount"] = [_("Must be greater than zero.")]
    if ends_on is not None and ends_on < data.starts_on:
        errors["ends_on"] = [_("Must not be before the first day.")]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    batch = uuid.uuid4()
    with transaction.atomic():
        people = resolve(data.target, on=data.starts_on, actor=actor, permission=GIVE)
        clash = (overlapping_assignments(people, item, data.starts_on, ends_on)
                 .select_related("employee").first())
        if clash is not None:
            raise ValidationError(
                _("%(name)s already has %(item)s over some of these days.")
                % {"name": clash.employee.name, "item": item.name},
                fields={"starts_on": [_("The item already runs over some of these days.")]})
        return PayItemAssignment.objects.bulk_create([
            PayItemAssignment(employee=employee, item=item, frequency=data.frequency,
                              amount=data.amount, starts_on=data.starts_on, ends_on=ends_on,
                              note=data.note.strip(), batch=batch,
                              created_by=getattr(actor, "user", None))
            for employee in people])


def _locked_rows(assignment_id: int, whole_batch: bool, actor):
    entry = PayItemAssignment.objects.filter(pk=assignment_id).first()
    if entry is None:
        raise NotFound(_("Not found."))
    rows = (PayItemAssignment.objects.filter(batch=entry.batch) if whole_batch
            else PayItemAssignment.objects.filter(pk=entry.pk))
    return entry, rows.filter(employee__in=visible_employees(actor, GIVE),
                              status=AssignmentStatus.ACTIVE).select_for_update()


def end_assignment(assignment_id: int, ends_on: date, *, actor=None) -> PayItemAssignment:
    """Stop a recurring item after `ends_on`. Days an approved payroll paid stay as they are."""
    if actor is not None:
        actor.require(GIVE)
    with transaction.atomic():
        entry, rows = _locked_rows(assignment_id, False, actor)
        row = rows.first()
        if row is None:
            raise Conflict(_("Already cancelled."), code="COMPENSATION_ENTRY_STATE")
        if row.frequency == ItemFrequency.ONCE:
            raise ValidationError(_("A one-time item has no end; cancel it instead."),
                                  fields={"ends_on": [_("Cancel it instead.")]})
        if ends_on < row.starts_on:
            raise ValidationError(_("Please correct the highlighted fields."),
                                  fields={"ends_on": [_("Must not be before the first day.")]})
        locks.ensure_open(row.employee_id, ends_on + timedelta(days=1),
                          row.ends_on or date.max)
        row.ends_on = ends_on
        row.updated_by = getattr(actor, "user", None)
        row.save(update_fields=["ends_on", "updated_by", "updated_at"])
        return row


def cancel_assignment(assignment_id: int, *, whole_batch: bool = False, actor=None) -> int:
    """Cancel an assignment, or every one given with it, if no approved payroll paid any of it.
    Returns how many were cancelled."""
    if actor is not None:
        actor.require(GIVE)
    with transaction.atomic():
        _entry, rows = _locked_rows(assignment_id, whole_batch, actor)
        rows = list(rows)
        if not rows:
            raise Conflict(_("Already cancelled."), code="COMPENSATION_ENTRY_STATE")
        for row in rows:
            locks.ensure_unpaid("compensation.PayItemAssignment", row.pk)
        return PayItemAssignment.objects.filter(pk__in=[r.pk for r in rows]).update(
            status=AssignmentStatus.CANCELLED, updated_by=getattr(actor, "user", None))
