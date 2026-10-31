"""Clients as the console reads them. A client's own data is read inside its tenant_context."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.core.tenancy import tenant_context
from apps.platform.tenants.models import Tenant, TenantDomain, TenantStatus

LIVE_STATUSES = (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


def find_client(pk: int) -> Tenant | None:
    return Tenant.objects.select_related("plan").prefetch_related("domains").filter(
        pk=pk).first()


def search_clients(term: str, status: str, plan_code: str) -> QuerySet[Tenant]:
    queryset = Tenant.objects.select_related("plan").prefetch_related("domains").order_by("name")
    if term:
        queryset = queryset.filter(Q(name__icontains=term) | Q(slug__icontains=term)
                                   | Q(contact_name__icontains=term)
                                   | Q(contact_email__icontains=term)
                                   | Q(domains__domain__icontains=term)).distinct()
    if status in TenantStatus.values:
        queryset = queryset.filter(status=status)
    if plan_code:
        queryset = queryset.filter(plan_id=plan_code)
    return queryset


def live_clients() -> list[Tenant]:
    return list(Tenant.objects.filter(status__in=LIVE_STATUSES))


def primary_domain(tenant: Tenant) -> str | None:
    domain = next((d for d in tenant.domains.all() if d.is_primary), None)
    return domain.domain if domain else None


def client_domains(tenant: Tenant) -> QuerySet[TenantDomain]:
    return tenant.domains.order_by("-is_primary", "domain")


def find_domain(tenant: Tenant, domain_id: int) -> TenantDomain | None:
    return tenant.domains.filter(pk=domain_id).first()


def client_profile(tenant: Tenant):
    """The client's own company settings. A purged client has none to read."""
    from apps.org.models import TenantProfile

    if tenant.status == TenantStatus.PURGED:
        return None
    with tenant_context(tenant.id):
        return TenantProfile.objects.first()


def client_owners(tenant: Tenant) -> list:
    from apps.iam.catalog import OWNER
    from apps.iam.models import Membership

    with tenant_context(tenant.id):
        return list(Membership.objects.select_related("user").filter(
            roles__role__code=OWNER).order_by("username"))
