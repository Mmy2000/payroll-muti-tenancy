"""What staff do to a client from the console."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.media import replace_file
from apps.core.tenancy import tenant_context
from apps.platform.tenants.models import Plan, Tenant, TenantDomain
from apps.platform.tenants.services import record

from .provisioning import ProvisionTenantCommand, provision_tenant

LIMIT_FIELDS = ("plan", "trial_ends_on", "max_branches", "max_users", "max_app_logins",
                "contact_name", "contact_email", "contact_phone", "notes")


def attr(name: str) -> str:
    """Form field → Tenant attribute (the plan is stored by its code)."""
    return "plan_id" if name == "plan" else name


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
