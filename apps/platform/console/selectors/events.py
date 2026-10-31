"""What platform staff did (PlatformEvent), newest first."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.platform.tenants.models import PlatformEvent, Tenant


def platform_events(tenant_id: int | None = None) -> QuerySet[PlatformEvent]:
    queryset = PlatformEvent.objects.select_related("actor", "tenant")
    if tenant_id is not None:
        queryset = queryset.filter(tenant_id=tenant_id)
    return queryset


def client_events(tenant: Tenant) -> QuerySet[PlatformEvent]:
    return tenant.events.select_related("actor")[:12]
