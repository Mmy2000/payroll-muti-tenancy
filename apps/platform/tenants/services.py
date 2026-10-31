"""Tenant provisioning (a new client with its domain, profile, head office, roles and owner) and
what staff change from the console: clients, domains, plans, features and platform settings.
Each staff act leaves a PlatformEvent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core.errors import ValidationError
from apps.core.media import replace_file
from apps.core.tenancy import tenant_context

from . import features as feature_registry
from .models import (
    RESERVED_SLUGS,
    Plan,
    PlanFeature,
    PlatformEvent,
    PlatformSettings,
    Tenant,
    TenantDomain,
    TenantStatus,
    WhatsAppService,
    ensure_plans,
)
from .validators import check_link

LIMIT_FIELDS = ("plan", "trial_ends_on", "max_branches", "max_users", "max_app_logins",
                "contact_name", "contact_email", "contact_phone", "notes")


def attr(name: str) -> str:
    """Form field → Tenant attribute (the plan is stored by its code)."""
    return "plan_id" if name == "plan" else name


def record(actor, action: str, tenant: Tenant | None = None, **detail) -> None:
    PlatformEvent.objects.create(actor=actor, tenant=tenant, action=action,
                                 detail={k: str(v) for k, v in detail.items()})


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
    from apps.iam.catalog import OWNER
    from apps.iam.models import Membership, User
    from apps.iam.services import assign_role, seed_system_roles
    from apps.org.models import Branch, TenantProfile

    slug = cmd.slug.strip().lower()
    if slug in RESERVED_SLUGS:
        raise ValidationError(_("'%(slug)s' is reserved.") % {"slug": slug},
                              fields={"slug": [_("Reserved.")]})
    existing = (User.objects.filter(email__iexact=cmd.owner_email).first()
                if cmd.owner_email else None)
    if existing is not None:
        check_link(existing, cmd)

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


def create_client(cmd: ProvisionTenantCommand, *, limits: dict, actor) -> Tenant:
    """Sign a client up: its workspace, then its plan, limits and contact details."""
    with transaction.atomic():
        tenant = provision_tenant(cmd)
        for name in LIMIT_FIELDS:
            setattr(tenant, attr(name), limits[name] if limits[name] is not None else
                    Tenant._meta.get_field(name).get_default())
        plan = Plan.objects.get(code=tenant.plan_id)
        if tenant.trial_ends_on is None and plan.trial_days:
            tenant.trial_ends_on = timezone.localdate() + timedelta(days=plan.trial_days)
        tenant.save()
    record(actor, "tenant.created", tenant, slug=tenant.slug, plan=tenant.plan_id)
    return tenant


def update_client(tenant: Tenant, *, data: dict, actor) -> Tenant:
    before = {name: getattr(tenant, attr(name)) for name in ("name", *LIMIT_FIELDS)}
    tenant.name = data["name"]
    for name in LIMIT_FIELDS:
        setattr(tenant, attr(name), data[name])
    tenant.save()
    changed = {name: getattr(tenant, attr(name)) for name in before
               if getattr(tenant, attr(name)) != before[name]}
    record(actor, "tenant.updated", tenant, **changed)
    return tenant


def update_client_profile(tenant: Tenant, *, data: dict, actor):
    """Change the settings kept in the client's own data. None if it has no profile."""
    from apps.org.models import TenantProfile

    data = dict(data)
    logo = data.pop("logo")
    with tenant_context(tenant.id):
        profile = TenantProfile.objects.first()
        if profile is None:
            return None
        for name, value in data.items():
            setattr(profile, name, value)
        replace_file(profile, "logo", logo)
        profile.save()
    if logo is not None:
        data["logo"] = _("removed") if logo is False else logo.name
    record(actor, "profile.updated", tenant, **data)
    return profile


def set_client_status(tenant: Tenant, *, status: str, actor) -> Tenant:
    if tenant.status == status:
        return tenant
    previous = tenant.status
    tenant.status = status
    tenant.save(update_fields=["status", "updated_at"])
    record(actor, "tenant.status", tenant, before=previous, after=status)
    return tenant


def set_traffic_limit(tenant: Tenant, *, limit: int | None, actor) -> Tenant:
    before = tenant.requests_per_minute
    tenant.requests_per_minute = limit
    tenant.save(update_fields=["requests_per_minute", "updated_at"])
    if tenant.requests_per_minute != before:
        record(actor, "traffic.limit", tenant,
               before="" if before is None else before,
               after="" if tenant.requests_per_minute is None
               else tenant.requests_per_minute)
    return tenant


def add_domain(tenant: Tenant, *, domain: str, actor) -> TenantDomain:
    row = TenantDomain.objects.create(tenant=tenant, domain=domain)
    record(actor, "domain.added", tenant, domain=domain)
    return row


def remove_domain(tenant: Tenant, *, domain: TenantDomain, actor) -> None:
    record(actor, "domain.removed", tenant, domain=domain.domain)
    domain.delete()


def _along_with(others) -> dict:
    return {"also": ", ".join(f.key for f in others)} if others else {}


def set_plan_feature(plan: Plan, *, key: str, enabled: bool, actor) -> tuple:
    """Returns the other features changed with it."""
    with transaction.atomic():
        others = feature_registry.set_for_plan(plan, key, enabled)
    record(actor, "feature.plan", None, plan=plan.code, feature=key, enabled=enabled,
           **_along_with(others))
    return others


def set_client_feature(tenant: Tenant, *, key: str, state: str, actor) -> tuple:
    """`state` is on, off or default (back to its plan). Returns the other features changed."""
    with transaction.atomic():
        others = feature_registry.set_for_client(tenant, key,
                                                 None if state == "default" else state == "on")
    record(actor, "feature.client", tenant, feature=key, state=state, **_along_with(others))
    return others


def save_plan(plan: Plan, *, features: dict[str, bool], changes: dict, created: bool,
              actor) -> Plan:
    """Save a plan and its choice for each feature. `changes` is what the event lists."""
    with transaction.atomic():
        plan.save()
        for key, enabled in features.items():
            PlanFeature.objects.update_or_create(plan=plan, key=key,
                                                 defaults={"enabled": enabled})
    feature_registry.forget()
    record(actor, "plan.created" if created else "plan.updated", None, plan=plan.code, **changes)
    return plan


def delete_plan(plan: Plan, *, clients: list[Tenant], move_to: str, actor) -> None:
    """Delete a plan. Its clients (if any) move to another plan first, in the same step."""
    target = Plan.objects.get(code=move_to)
    with transaction.atomic():
        for tenant in clients:
            tenant.plan = target
            tenant.save(update_fields=["plan", "updated_at"])
            record(actor, "tenant.updated", tenant, plan=target.code)
        if plan.is_default:
            target.is_default, target.is_active = True, True
            target.save()
        code = plan.code
        plan.delete()
    feature_registry.forget()
    record(actor, "plan.deleted", None, plan=code, moved_to=target.code, clients=len(clients))


def save_platform_settings(row: PlatformSettings, *, old_logos: dict[str, str],
                           deleted_links: list, saved_links: list, changes: dict,
                           actor) -> PlatformSettings:
    """Save the branding and the sidebar links, and drop the logo files that were replaced."""
    row.save()
    for link in deleted_links:
        link.delete()
    for link in saved_links:
        link.save()
    PlatformSettings.objects.get(pk=1).save()  # drops the cached copy everywhere
    for name, old in old_logos.items():
        if old and old != getattr(row, name).name:
            default_storage.delete(old)
    record(actor, "platform.settings", None, **changes)
    return row


def save_whatsapp_settings(service: WhatsAppService, *, secret: str, changes: dict,
                           actor) -> WhatsAppService:
    """`secret` is a pasted key. Without one, a gateway switched on with no key is given one."""
    if secret:
        service.secret = secret
    elif service.enabled and not service.key:
        service.new_secret()
    service.save()
    record(actor, "whatsapp.settings", None, **changes)
    return service


def replace_whatsapp_key(service: WhatsAppService, *, actor) -> WhatsAppService:
    service.new_secret()
    service.save()
    record(actor, "whatsapp.key")
    return service
