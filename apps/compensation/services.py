"""Pay items: the catalogue, and giving an item to employees for one or more months."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.months import months
from apps.employees.services import visible_employees
from apps.employees.targets import Target, resolve

from .models import EntryStatus, PayItem, PayItemBasis, PayItemEntry, PayItemKind

GIVE = "compensation.entry.manage"
MAX_MONTHS = 24


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


# --- giving items for a month --------------------------------------------------------------


@dataclass(frozen=True)
class EntryInput:
    item_id: int
    target: Target
    first_month: date  # any day of the first month
    months: int
    amount: Decimal
    note: str = ""


def give_items(data: EntryInput, *, actor=None) -> list[PayItemEntry]:
    """The item for each employee the target means (employed on the first day of the first
    month) and each month, sharing a batch. A month that already has the item is refused."""
    if actor is not None:
        actor.require(GIVE)
    item = PayItem.objects.filter(pk=data.item_id, is_active=True).first()
    errors = {}
    if item is None:
        errors["item_id"] = [_("Choose an active pay item.")]
    if data.amount <= 0:
        errors["amount"] = [_("Must be greater than zero.")]
    if not 1 <= data.months <= MAX_MONTHS:
        errors["months"] = [_("From 1 to %(count)s months.") % {"count": MAX_MONTHS}]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    first = data.first_month.replace(day=1)
    batch = uuid.uuid4()
    with transaction.atomic():
        people = resolve(data.target, on=first, actor=actor, permission=GIVE)
        span = months(first, data.months)
        clash = (PayItemEntry.objects.filter(employee__in=people, item=item, month__in=span,
                                             status=EntryStatus.ACTIVE)
                 .select_related("employee").first())
        if clash is not None:
            raise ValidationError(
                _("%(name)s already has %(item)s for %(month)s.")
                % {"name": clash.employee.name, "item": item.name,
                   "month": clash.month.isoformat()[:7]},
                fields={"first_month": [_("Already given for one of these months.")]})
        return PayItemEntry.objects.bulk_create([
            PayItemEntry(employee=employee, item=item, month=month, amount=data.amount,
                         note=data.note.strip(), batch=batch,
                         created_by=getattr(actor, "user", None))
            for employee in people for month in span])


def cancel_entry(entry_id: int, *, whole_batch: bool = False, actor=None) -> int:
    """Cancel an entry, or every entry given with it. Returns how many were cancelled."""
    # TODO(phase 4): refuse once a posted payroll covers the entry's month.
    if actor is not None:
        actor.require(GIVE)
    with transaction.atomic():
        entry = PayItemEntry.objects.filter(pk=entry_id).first()
        if entry is None:
            raise NotFound(_("Not found."))
        rows = (PayItemEntry.objects.filter(batch=entry.batch) if whole_batch
                else PayItemEntry.objects.filter(pk=entry.pk))
        rows = rows.filter(employee__in=visible_employees(actor, GIVE),
                           status=EntryStatus.ACTIVE)
        if not rows.select_for_update().exists():
            raise Conflict(_("Already cancelled."), code="COMPENSATION_ENTRY_STATE")
        return rows.update(status=EntryStatus.CANCELLED, updated_by=getattr(actor, "user", None))
