from __future__ import annotations

from collections.abc import Iterable

from django.core.cache import cache

from apps.core.tenancy import get_current_tenant_id

from .models import Tenant

HOST_CACHE_SECONDS = 60


def _key(host: str) -> str:
    return f"platform:tenant-host:{host}"


def tenant_for_host(host: str):
    """The Tenant a (lower-cased, port-less) host belongs to, or None. Cached for 60 s;
    TenantDomain/Tenant saves drop the entry so status changes apply immediately."""
    from .models import TenantDomain

    cached = cache.get(_key(host))
    if cached is not None:
        return cached or None  # "" caches a miss

    domain = TenantDomain.objects.select_related("tenant").filter(domain=host).first()
    tenant = domain.tenant if domain else None
    cache.set(_key(host), tenant or "", HOST_CACHE_SECONDS)
    return tenant


def forget_hosts(hosts: Iterable[str]) -> None:
    cache.delete_many([_key(h) for h in hosts])


def current_tenant() -> Tenant | None:
    tenant_id = get_current_tenant_id()
    return (Tenant.objects.select_related("plan").filter(pk=tenant_id).first()
            if tenant_id else None)
