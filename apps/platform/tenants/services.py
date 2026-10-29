"""Tenant provisioning: a new client with its domain, profile, head office, roles and owner."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core.errors import ValidationError
from apps.core.tenancy import tenant_context

from .models import RESERVED_SLUGS, Tenant, TenantDomain, TenantStatus, ensure_plans


def _check_link(user, cmd: ProvisionTenantCommand) -> None:
    """An existing login becomes this workspace's owner only when asked, never a staff login,
    and never with a password typed for it (it would be ignored)."""
    if user.is_platform_staff:
        raise ValidationError(_("Platform staff logins can't own a workspace. Use another email."),
                              fields={"owner_email": [_("A platform staff login.")]},
                              code="TENANT_OWNER_IS_STAFF")
    if not cmd.link_existing_owner:
        raise ValidationError(
            _("This email already has a login. Add this workspace to that login, or use "
              "another email."), fields={"owner_email": [_("Already has a login.")]},
            code="TENANT_OWNER_EXISTS")
    if cmd.owner_password:
        raise ValidationError(
            _("That login keeps its own password: leave the password empty."),
            fields={"owner_password": [_("Leave empty.")]}, code="TENANT_OWNER_PASSWORD")


@dataclass(frozen=True)
class ProvisionTenantCommand:
    slug: str
    name: str
    domain: str
    owner_username: str
    owner_password: str | None
    owner_email: str | None = None
    # The owner already has a login (same email) and this workspace is added to it: it keeps
    # its own password. Never implied: a login is only shared when asked for (ADR-022).
    link_existing_owner: bool = False
    owner_display_name: str = ""
    head_office_name: str | None = None  # defaults to "Head office" in the tenant's language
    functional_currency: str = "EGP"
    timezone: str = "Africa/Cairo"
    locale: str = "ar"
    country: str = "EG"  # ISO 3166 alpha-2; default region for phone numbers
    activate: bool = True


def provision_tenant(cmd: ProvisionTenantCommand) -> Tenant:
    """Create a tenant with its primary domain, profile, head-office branch, system roles, owner
    and each app's starting data (apps.core.seeding).

    The owner is a global User plus a Membership carrying the tenant-local username and the
    Owner role. An existing login with that email is used only with `link_existing_owner`
    (it keeps its password), and never a staff login (ADR-022).
    Seeded names (roles, head office…) are written in the tenant's language.
    """
    from apps.core.seeding import run_seeds
    from apps.iam.models import Membership, User
    from apps.iam.services import OWNER, assign_role, seed_system_roles
    from apps.org.models import Branch, TenantProfile

    slug = cmd.slug.strip().lower()
    if slug in RESERVED_SLUGS:
        raise ValidationError(_("'%(slug)s' is reserved.") % {"slug": slug},
                              fields={"slug": [_("Reserved.")]})
    existing = (User.objects.filter(email__iexact=cmd.owner_email).first()
                if cmd.owner_email else None)
    if existing is not None:
        _check_link(existing, cmd)

    with transaction.atomic(), translation.override(cmd.locale):
        ensure_plans()
        tenant = Tenant(slug=slug, name=cmd.name, status=TenantStatus.PROVISIONING)
        tenant.full_clean()
        tenant.save()
        TenantDomain.objects.create(
            tenant=tenant, domain=cmd.domain, is_primary=True, verified_at=timezone.now()
        )

        with tenant_context(tenant.id):
            TenantProfile.objects.create(
                display_name=cmd.name,
                legal_name=cmd.name,
                functional_currency=cmd.functional_currency,
                timezone=cmd.timezone,
                locale=cmd.locale,
                country=cmd.country.upper(),
            )
            head_office = Branch.objects.create(
                code=1, name=cmd.head_office_name or _("Head office"), is_head_office=True
            )
            roles = seed_system_roles()
            run_seeds(country=cmd.country.upper(), currency=cmd.functional_currency,
                      head_office=head_office)

            user = existing
            if user is None:
                user = User.objects.create_user(
                    email=cmd.owner_email,
                    password=cmd.owner_password,
                    display_name=cmd.owner_display_name or cmd.owner_username,
                )
            owner = Membership.objects.create(
                user=user, username=cmd.owner_username, default_branch=head_office
            )
            assign_role(owner, roles[OWNER])

        if cmd.activate:
            tenant.status = TenantStatus.ACTIVE
            tenant.save(update_fields=["status", "updated_at"])

    return tenant
