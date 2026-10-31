"""Branches and departments."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, ValidationError
from apps.core.media import replace_file

from .models import Branch, Department, DepartmentBranch, Position, TenantProfile
from .permissions import BRANCH_MANAGE, DEPARTMENT_MANAGE, POSITION_MANAGE
from .selectors import next_department_code
from .validators import check_department, check_position


@dataclass(frozen=True)
class BranchInput:
    code: int
    name: str
    phone: str = ""
    address: str = ""
    is_head_office: bool | None = None  # None: stays as it is
    # Where it is, for the mobile app's geofence (both or neither).
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    radius_m: int = 200


def _save(branch: Branch, data: BranchInput, actor) -> Branch:
    branch.code = data.code
    branch.name = data.name.strip()
    branch.phone = data.phone.strip()
    branch.address = data.address.strip()
    if data.is_head_office is not None:
        branch.is_head_office = data.is_head_office
    if (data.latitude is None) != (data.longitude is None):
        raise ValidationError(_("Please correct the highlighted fields."),
                              fields={"longitude": [_("Enter both the latitude and the "
                                                      "longitude, or neither.")]})
    branch.latitude, branch.longitude = data.latitude, data.longitude
    branch.radius_m = data.radius_m
    branch.updated_by = getattr(actor, "user", None)
    branch._stamp_tenant()
    with transaction.atomic():
        if data.is_head_office:
            # Exactly one head office: moving the flag clears it elsewhere first.
            Branch.objects.filter(is_head_office=True).exclude(pk=branch.pk).update(
                is_head_office=False)
        try:
            branch.full_clean()
        except DjangoValidationError as exc:
            raise ValidationError(_("Please correct the highlighted fields."),
                                  fields=exc.message_dict) from exc
        branch.save()
    return branch


def create_branch(data: BranchInput, *, actor=None) -> Branch:
    if actor is not None:
        actor.require_everywhere(BRANCH_MANAGE)
    from .limits import check_branch_limit

    check_branch_limit()
    return _save(Branch(created_by=getattr(actor, "user", None)), data, actor)


def update_branch(branch_id: int, data: BranchInput, *, actor=None) -> Branch:
    """A member limited to some branches edits those. Which branch is the head office concerns
    them all."""
    if actor is not None:
        actor.require(BRANCH_MANAGE)
    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        raise NotFound(_("Not found."))
    if actor is not None:
        actor.require(BRANCH_MANAGE, branch=branch.pk)
        if data.is_head_office not in (None, branch.is_head_office):
            actor.require_everywhere(BRANCH_MANAGE)
    return _save(branch, data, actor)


def set_branch_active(branch_id: int, active: bool, *, actor=None) -> Branch:
    if actor is not None:
        actor.require(BRANCH_MANAGE)
    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        raise NotFound(_("Not found."))
    if actor is not None:
        actor.require(BRANCH_MANAGE, branch=branch.pk)
    if not active and branch.is_head_office:
        raise ValidationError(_("The head office cannot be deactivated."),
                              code="ORG_HEAD_OFFICE_ACTIVE")
    if active and not branch.is_active:
        from .limits import check_branch_limit

        check_branch_limit()
    branch.is_active = active
    branch.save(update_fields=["is_active", "updated_at"])
    return branch


@dataclass(frozen=True)
class DepartmentInput:
    name: str
    branch_ids: tuple[int, ...]
    code: int | None = None  # None: the company's next code


def _require_branches(actor, branch_ids) -> None:
    if actor is not None:
        for branch_id in branch_ids:
            actor.require(DEPARTMENT_MANAGE, branch=branch_id)


def save_department(data: DepartmentInput, *, department_id: int | None = None,
                    actor=None) -> Department:
    """Create a department in its branches, or update one when `department_id` is given. A
    change reaches every branch it is in, so the member needs them all."""
    wanted = set(data.branch_ids)
    _require_branches(actor, wanted)
    if department_id is None:
        department = Department(created_by=getattr(actor, "user", None))
    else:
        department = Department.objects.filter(pk=department_id).first()
        if department is None:
            raise NotFound(_("Not found."))
        _require_branches(actor, department.branch_ids)
    errors = check_department(department, data)
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    department.code = data.code or department.code or next_department_code()
    department.name = data.name.strip()
    department.updated_by = getattr(actor, "user", None)
    department._stamp_tenant()
    try:
        department.full_clean()
    except DjangoValidationError as exc:
        raise ValidationError(_("Please correct the highlighted fields."),
                              fields=exc.message_dict) from exc
    with transaction.atomic():
        department.save()
        department.placements.exclude(branch_id__in=wanted).delete()
        for branch_id in sorted(wanted - set(department.branch_ids)):
            DepartmentBranch.objects.create(department=department, branch_id=branch_id)
    return department


def set_department_active(department_id: int, active: bool, *, actor=None) -> Department:
    department = Department.objects.filter(pk=department_id).first()
    if department is None:
        raise NotFound(_("Not found."))
    _require_branches(actor, department.branch_ids)
    department.is_active = active
    department.save(update_fields=["is_active", "updated_at"])
    return department


def save_company(profile: TenantProfile, *, display_name: str, accent: str, logo,
                 app_qr_minutes: int | None = None) -> TenantProfile:
    """The client's name on screens, colour and logo; `app_qr_minutes` when it was on the form."""
    profile.display_name = display_name
    profile.accent = accent
    if app_qr_minutes is not None:
        profile.app_qr_minutes = app_qr_minutes
    replace_file(profile, "logo", logo)
    profile.save()
    return profile


@dataclass(frozen=True)
class PositionInput:
    name: str
    department_id: int | None = None


def save_position(data: PositionInput, *, position_id: int | None = None, actor=None) -> Position:
    if actor is not None:
        actor.require(POSITION_MANAGE)
    if position_id is None:
        position = Position(created_by=getattr(actor, "user", None))
    else:
        position = Position.objects.filter(pk=position_id).first()
        if position is None:
            raise NotFound(_("Not found."))
    errors = check_position(position, data)
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    position.name = data.name.strip()
    position.department_id = data.department_id
    position.updated_by = getattr(actor, "user", None)
    position.save()
    return position


def set_position_active(position_id: int, active: bool, *, actor=None) -> Position:
    if actor is not None:
        actor.require(POSITION_MANAGE)
    position = Position.objects.filter(pk=position_id).first()
    if position is None:
        raise NotFound(_("Not found."))
    position.is_active = active
    position.save(update_fields=["is_active", "updated_at"])
    return position
