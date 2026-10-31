"""Members, roles and assignments.

Guard rails enforced here (not in the UI):
* no privilege escalation: an actor can only grant permissions they hold themselves, and only
  wildcard (Owner) actors can hand out the Owner role;
* the workspace always keeps at least one active Owner;
* an email already used by another account is refused (invitations come later).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, ValidationError

from .catalog import (
    APP_SIGNIN,
    EMPLOYEE,
    MANAGER,
    OWNER,
    VIEWER,
    WILDCARD,
    permissions,
)
from .limits import check_room_for, is_app_login
from .models import (
    SYSTEM_ROLE_NAMES,
    Membership,
    MembershipRole,
    MembershipRoleBranch,
    MembershipStatus,
    Role,
    RolePermission,
    User,
)
from .validators import (
    assignment_branches,
    clean_permissions,
    ensure_an_owner_remains,
    ensure_can_act_on,
    ensure_can_grant,
    ensure_needs_met,
    ensure_not_shared,
    member_role_codes,
    role_codes,
    unique_role_code,
    validate_member,
)


def system_role_templates() -> dict[str, tuple[str, str, list[str]]]:
    catalog = permissions()
    viewing = [c for c in catalog if c.endswith(".view")]
    managing = [c for c in catalog if not c.startswith("admin.")] + ["admin.users.view"]
    names = {code: (str(n), str(d)) for code, (n, d) in SYSTEM_ROLE_NAMES.items()}
    return {
        OWNER: (*names[OWNER], [WILDCARD]),
        MANAGER: (*names[MANAGER], managing),
        VIEWER: (*names[VIEWER], viewing),
        EMPLOYEE: (*names[EMPLOYEE], [c for c in (APP_SIGNIN,) if c in catalog]),
    }


def seed_system_roles() -> dict[str, Role]:
    """Create the Owner/Manager/Viewer roles for a new tenant. Idempotent."""
    roles = {}
    for code, (name, description, grants) in system_role_templates().items():
        role, created = Role.objects.get_or_create(
            code=code, defaults={"name": name, "description": description, "is_system": True}
        )
        if created:
            RolePermission.objects.bulk_create(
                [RolePermission(role=role, permission=p) for p in grants]
            )
        roles[code] = role
    return roles


# --- guard rails ------------------------------------------------------------------------------


# --- roles ------------------------------------------------------------------------------------


def set_role_permissions(role: Role, codes: list[str], *, actor=None) -> None:
    if role.code == OWNER:
        raise ValidationError(_("The Owner role cannot be changed."), code="IAM_OWNER_LOCKED")
    codes = clean_permissions(codes)
    if role.code == EMPLOYEE and codes != [APP_SIGNIN]:
        # A member with this role alone counts as an app login, not an office user.
        raise ValidationError(_("The Employee (app) role only signs in to the mobile app."),
                              code="IAM_EMPLOYEE_LOCKED")
    if actor is not None:
        ensure_needs_met(codes)
    ensure_can_grant(actor, codes)
    with transaction.atomic():
        role.grants.all().delete()
        RolePermission.objects.bulk_create([RolePermission(role=role, permission=c) for c in codes])


def create_role(name: str, description: str, codes: list[str], *, actor=None) -> Role:
    if actor is not None:
        actor.require("admin.roles.manage")
    name = name.strip()
    if not name:
        raise ValidationError(_("Please correct the highlighted fields."),
                              fields={"name": [_("This field is required.")]})
    with transaction.atomic():
        role = Role.objects.create(code=unique_role_code(name), name=name,
                                   description=description.strip())
        set_role_permissions(role, codes, actor=actor)
    return role


def update_role(role_id: int, name: str, description: str, codes: list[str], *,
                actor=None) -> Role:
    if actor is not None:
        actor.require("admin.roles.manage")
    role = Role.objects.filter(pk=role_id).first()
    if role is None:
        raise NotFound(_("Not found."))
    if role.code == OWNER:
        raise ValidationError(_("The Owner role cannot be changed."), code="IAM_OWNER_LOCKED")
    with transaction.atomic():
        role.name = name.strip() or role.name
        role.description = description.strip()
        role.save(update_fields=["name", "description", "updated_at"])
        set_role_permissions(role, codes, actor=actor)
    return role


def delete_role(role_id: int, *, actor=None) -> None:
    if actor is not None:
        actor.require("admin.roles.manage")
    role = Role.objects.filter(pk=role_id).first()
    if role is None:
        raise NotFound(_("Not found."))
    if role.is_system:
        raise ValidationError(_("Built-in roles cannot be deleted."), code="IAM_SYSTEM_ROLE")
    if role.assignments.exists():
        raise ValidationError(_("Remove this role from its members first."),
                              code="IAM_ROLE_IN_USE")
    role.delete()


# --- members ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class RoleAssignmentInput:
    role_id: int
    branch_ids: tuple[int, ...] | None = None  # None = every branch


@dataclass(frozen=True)
class MemberInput:
    username: str
    display_name: str
    email: str = ""
    phone: str = ""
    default_branch_id: int | None = None
    roles: tuple[RoleAssignmentInput, ...] = ()


def _apply_roles(membership: Membership, data: MemberInput, clean: dict, actor) -> None:
    wanted = {a.role_id: a for a in data.roles}
    for role in clean["roles"].values():
        ensure_can_grant(actor, role_codes(role), wanted[role.pk].branch_ids)
    current = MembershipRole.objects.filter(membership=membership)
    for assignment in current.select_related("role").prefetch_related("branches"):
        # Taking a role or a branch away is also a grant decision: you can't strip powers you
        # don't hold.
        held = assignment_branches(assignment)
        kept = wanted.get(assignment.role_id)
        if kept is None or (set(kept.branch_ids) if kept.branch_ids is not None else None) != held:
            ensure_can_grant(actor, role_codes(assignment.role), held)
    current.exclude(role_id__in=wanted).delete()
    for role_id, assignment in wanted.items():
        branches = (None if assignment.branch_ids is None
                    else [clean["branches"][b] for b in assignment.branch_ids])
        assign_role(membership, clean["roles"][role_id], branches=branches)


def create_member(data: MemberInput, password: str, *, actor=None) -> Membership:
    if actor is not None:
        actor.require("admin.users.manage")
    clean = validate_member(data, None)
    check_room_for(role.code for role in clean["roles"].values())
    try:
        validate_password(password)
    except DjangoValidationError as exc:
        raise ValidationError(_("Please correct the highlighted fields."),
                              fields={"password": list(exc.messages)}) from exc
    with transaction.atomic():
        user = User.objects.create_user(email=clean["email"], password=password,
                                        display_name=data.display_name.strip(),
                                        phone=data.phone.strip() or None)
        membership = Membership.objects.create(
            user=user, username=clean["username"], default_branch=clean["default_branch"],
            created_by=getattr(actor, "user", None),
        )
        _apply_roles(membership, data, clean, actor)
    return membership


def update_member(membership_id: int, data: MemberInput, *, actor=None) -> Membership:
    if actor is not None:
        actor.require("admin.users.manage")
    with transaction.atomic():
        membership = (Membership.objects.select_for_update().select_related("user")
                      .filter(pk=membership_id).first())
        if membership is None:
            raise NotFound(_("Not found."))
        clean = validate_member(data, membership.user)
        new_codes = {role.code for role in clean["roles"].values()}
        if (membership.status == MembershipStatus.ACTIVE
                and is_app_login(member_role_codes(membership)) != is_app_login(new_codes)):
            check_room_for(new_codes)  # an app login becoming an office user, or back
        user = membership.user
        if clean["email"] != user.email or (data.phone.strip() or None) != user.phone:
            ensure_not_shared(user, "email")
        user.display_name = data.display_name.strip()
        user.email = clean["email"]
        user.phone = data.phone.strip() or None
        user.save(update_fields=["display_name", "email", "phone"])
        membership.username = clean["username"]
        membership.default_branch = clean["default_branch"]
        membership.updated_by = getattr(actor, "user", None)
        membership.save()
        _apply_roles(membership, data, clean, actor)
        ensure_an_owner_remains()
    return membership


def set_member_status(membership_id: int, status: str, *, actor=None) -> Membership:
    if actor is not None:
        actor.require("admin.users.manage")
    if status not in MembershipStatus.values:
        raise ValidationError(_("Unknown status."))
    with transaction.atomic():
        membership = Membership.objects.select_for_update().filter(pk=membership_id).first()
        if membership is None:
            raise NotFound(_("Not found."))
        if actor is not None and membership.pk == actor.membership.pk:
            raise ValidationError(_("You cannot suspend yourself."), code="IAM_SELF_SUSPEND")
        ensure_can_act_on(membership, actor)
        if status == MembershipStatus.ACTIVE and membership.status != MembershipStatus.ACTIVE:
            check_room_for(member_role_codes(membership))  # back in: takes a place again
        membership.status = status
        membership.save(update_fields=["status", "updated_at"])
        ensure_an_owner_remains()
    return membership


def set_member_password(membership_id: int, password: str, *, actor=None) -> None:
    """Set a new password (existing sessions of that user end: Django rotates the auth hash)."""
    if actor is not None:
        actor.require("admin.users.manage")
    membership = Membership.objects.select_related("user").filter(pk=membership_id).first()
    if membership is None:
        raise NotFound(_("Not found."))
    ensure_can_act_on(membership, actor)
    ensure_not_shared(membership.user, "password")
    try:
        validate_password(password, user=membership.user)
    except DjangoValidationError as exc:
        raise ValidationError(_("Please correct the highlighted fields."),
                              fields={"password": list(exc.messages)}) from exc
    membership.user.set_password(password)
    membership.user.save(update_fields=["password"])


def assign_role(membership, role: Role, *, branches=None) -> MembershipRole:
    """Give `membership` the role in all branches (branches=None) or only in `branches`."""
    with transaction.atomic():
        assignment, _created = MembershipRole.objects.update_or_create(
            membership=membership, role=role, defaults={"all_branches": branches is None}
        )
        assignment.branches.all().delete()
        if branches is not None:
            MembershipRoleBranch.objects.bulk_create(
                [MembershipRoleBranch(assignment=assignment, branch=b) for b in branches]
            )
        return assignment
