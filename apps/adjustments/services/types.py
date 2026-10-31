"""The types of incentive and penalty a client uses."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, invalid_fields

from ..models import AdjustmentKind, AdjustmentType
from ..permissions import permission


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
