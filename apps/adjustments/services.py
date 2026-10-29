"""Incentives and penalties: their types, giving them to an employee, a department or a
branch, and cancelling them.

The kind decides the permission (`adjustments.incentive.*` or `adjustments.penalty.*`), so a
member may be allowed to give incentives and not penalties. The amount is worked out once, from
the pay in effect on the day (apps.adjustments.domain.amounts).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.history import in_effect
from apps.employees.services import visible_employees
from apps.employees.targets import Target, resolve

from .domain.amounts import METHODS, Pay
from .models import Adjustment, AdjustmentKind, AdjustmentStatus, AdjustmentType


def permission(kind: str, action: str) -> str:
    return f"adjustments.{kind}.{action}"


def _invalid(fields: dict) -> ValidationError:
    return ValidationError(_("Please correct the highlighted fields."), fields=fields)


# --- types ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeInput:
    kind: str
    code: int
    name: str


def save_type(data: TypeInput, *, type_id: int | None = None, actor=None) -> AdjustmentType:
    if data.kind not in AdjustmentKind.values:
        raise _invalid({"kind": [_("Choose incentive or penalty.")]})
    if actor is not None:
        actor.require(permission(data.kind, "manage"))
    name = data.name.strip()
    with transaction.atomic():
        found = AdjustmentType() if type_id is None else AdjustmentType.objects.filter(
            pk=type_id).select_for_update().first()
        if found is None:
            raise NotFound(_("Not found."))
        if found.pk and found.kind != data.kind:
            raise _invalid({"kind": [_("A type can't change kind.")]})
        others = AdjustmentType.objects.filter(kind=data.kind).exclude(pk=found.pk)
        errors = {}
        if not name:
            errors["name"] = [_("Enter a name.")]
        elif others.filter(name=name).exists():
            errors["name"] = [_("Another type has this name.")]
        if others.filter(code=data.code).exists():
            errors["code"] = [_("Another type has this code.")]
        if errors:
            raise _invalid(errors)
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


# --- giving --------------------------------------------------------------------------------


@dataclass(frozen=True)
class AdjustmentInput:
    type_id: int
    target: Target
    date: date
    method: str
    quantity: Decimal
    reason: str = ""


def give(data: AdjustmentInput, *, actor=None) -> list[Adjustment]:
    """One entry per employee the target means on the day, sharing a batch."""
    found = AdjustmentType.objects.filter(pk=data.type_id, is_active=True).first()
    errors = {}
    if found is None:
        errors["type_id"] = [_("Choose an active type.")]
    method = METHODS.get(data.method)
    if method is None:
        errors["method"] = [_("Choose how the amount is counted.")]
    if data.quantity <= 0:
        errors["quantity"] = [_("Must be greater than zero.")]
    if errors:
        raise _invalid(errors)
    manage = permission(found.kind, "manage")
    if actor is not None:
        actor.require(manage)
    batch = uuid.uuid4()
    with transaction.atomic():
        made = []
        for employee in resolve(data.target, on=data.date, actor=actor, permission=manage):
            pay = in_effect(employee.pay_history.all(), data.date)
            amount = method.amount(data.quantity, Pay(pay.basis, pay.salary, pay.hours_per_day))
            made.append(Adjustment(
                employee=employee, adjustment_type=found, kind=found.kind, date=data.date,
                method=method.key, quantity=data.quantity, amount=amount,
                reason=data.reason.strip(), batch=batch, created_by=getattr(actor, "user", None)))
        return Adjustment.objects.bulk_create(made)


def cancel(adjustment_id: int, *, whole_batch: bool = False, actor=None) -> int:
    """Cancel an entry, or every entry given with it. Returns how many were cancelled."""
    # TODO(phase 4): refuse once a posted payroll covers the entry's date.
    with transaction.atomic():
        entry = Adjustment.objects.filter(pk=adjustment_id).first()
        if entry is None:
            raise NotFound(_("Not found."))
        manage = permission(entry.kind, "manage")
        rows = (Adjustment.objects.filter(batch=entry.batch) if whole_batch
                else Adjustment.objects.filter(pk=entry.pk))
        if actor is not None:
            actor.require(manage)
            rows = rows.filter(employee__in=visible_employees(actor, manage))
        rows = rows.select_for_update()
        if not rows.filter(status=AdjustmentStatus.ACTIVE).exists():
            raise Conflict(_("Already cancelled."), code="ADJUSTMENTS_STATE")
        return rows.filter(status=AdjustmentStatus.ACTIVE).update(
            status=AdjustmentStatus.CANCELLED, updated_by=getattr(actor, "user", None))
