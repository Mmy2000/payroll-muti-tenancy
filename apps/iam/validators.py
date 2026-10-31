"""The rules on roles and members: nobody reaches above their own powers, an owner always
remains, and a member's details are valid."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core.errors import PermissionDenied, ValidationError

from .catalog import OWNER, WILDCARD, is_known_permission
from .models import Membership, MembershipRole, MembershipStatus, Role, User

if TYPE_CHECKING:
    from .services import MemberInput


def is_superior(actor) -> bool:
    return actor is None or WILDCARD in actor.grants


def ensure_can_grant(actor, codes) -> None:
    if is_superior(actor):
        return
    if WILDCARD in codes or any(not actor.can(code) for code in codes):
        raise PermissionDenied(_("You can only grant permissions you have yourself."),
                               code="IAM_ESCALATION")


def ensure_can_act_on(membership, actor) -> None:
    """Acting as a member, or letting someone in as them, takes the powers they hold."""
    for assignment in membership.roles.select_related("role"):
        ensure_can_grant(actor, role_codes(assignment.role))


def role_codes(role: Role) -> set[str]:
    return set(role.grants.values_list("permission", flat=True))


def ensure_an_owner_remains() -> None:
    active_owners = (MembershipRole.objects
                     .filter(role__code=OWNER, membership__status=MembershipStatus.ACTIVE)
                     .values("membership").distinct().count())
    if active_owners == 0:
        raise ValidationError(_("The workspace must keep at least one active owner."),
                              code="IAM_LAST_OWNER")


def clean_permissions(codes) -> list[str]:
    codes = sorted(set(codes))
    unknown = [c for c in codes if not is_known_permission(c) or c == WILDCARD]
    if unknown:
        raise ValidationError(_("Unknown permissions."), fields={"permissions": unknown})
    return codes


def unique_role_code(name: str) -> str:
    base = slugify(name)[:40] or "role"
    code, n = base, 1
    while Role.objects.filter(code=code).exists():
        n += 1
        code = f"{base}-{n}"
    return code


def ensure_not_shared(user: User, field: str) -> None:
    """A login also used for another workspace, or by Gweb's staff, is changed only by its
    owner: one workspace changing its password or email would let it into the others
    (ADR-022). The count comes from the database (a trigger keeps it)."""
    count = User.objects.filter(pk=user.pk).values_list("membership_count", flat=True).first()
    if user.is_platform_staff or (count or 0) > 1:
        raise ValidationError(
            _("Please correct the highlighted fields."), code="IAM_SHARED_LOGIN",
            fields={field: [_("This person uses the same login outside this workspace, so only "
                              "they can change its password or email.")]})


def validate_member(data: MemberInput, user: User | None) -> dict:
    from apps.org.models import Branch

    errors: dict[str, list[str]] = {}
    username = data.username.strip()
    try:
        UnicodeUsernameValidator()(username)
    except DjangoValidationError:
        errors["username"] = [_("Letters, digits and @/./+/-/_ only.")]
    if not username:
        errors["username"] = [_("This field is required.")]
    elif Membership.objects.filter(username=username).exclude(user=user).exists():
        errors["username"] = [_("This username is already taken in this workspace.")]
    if not data.display_name.strip():
        errors["display_name"] = [_("This field is required.")]

    email = data.email.strip().lower()
    if email:
        try:
            validate_email(email)
        except DjangoValidationError:
            errors["email"] = [_("Enter a valid email address.")]
        else:
            others = User.objects.filter(email__iexact=email).exclude(pk=getattr(user, "pk", None))
            if others.exists():
                errors["email"] = [_("This email already belongs to another account.")]
    phone = data.phone.strip()
    if phone and User.objects.filter(phone=phone).exclude(pk=getattr(user, "pk", None)).exists():
        errors["phone"] = [_("This phone number already belongs to another account.")]

    default_branch = None
    if data.default_branch_id is not None:
        default_branch = Branch.objects.filter(pk=data.default_branch_id).first()
        if default_branch is None:
            errors["default_branch"] = [_("Unknown branch.")]

    roles = {r.pk: r for r in Role.objects.filter(pk__in=[a.role_id for a in data.roles])}
    if len(roles) != len({a.role_id for a in data.roles}):
        errors["roles"] = [_("Unknown role.")]
    if not data.roles:
        errors["roles"] = [_("Give the member at least one role.")]

    branch_ids = {b for a in data.roles for b in (a.branch_ids or ())}
    branches = {b.pk: b for b in Branch.objects.filter(pk__in=branch_ids)}
    if len(branches) != len(branch_ids):
        errors["roles"] = [_("Unknown branch.")]

    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    return {"username": username, "email": email or None, "default_branch": default_branch,
            "roles": roles, "branches": branches}


def member_role_codes(membership: Membership) -> set[str]:
    return set(membership.roles.values_list("role__code", flat=True))
