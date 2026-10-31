"""Each client works in the time zone of its profile (org.TenantProfile.timezone): requests,
like background jobs (apps/platform/jobs/worker.py), run with it active, so `localtime()` and
`localdate()` give the client's clock. Attendance depends on it: a punch belongs to the work day
of the client's local time, not the server's."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

CACHE_SECONDS = 300


def _cache_key(tenant_id: int) -> str:
    return f"t:{tenant_id}:timezone"


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(settings.TIME_ZONE)


def tenant_zone_name(tenant_id: int) -> str:
    name = cache.get(_cache_key(tenant_id))
    if name is None:
        from apps.org.models import TenantProfile

        name = TenantProfile.objects.values_list("timezone", flat=True).first() or ""
        cache.set(_cache_key(tenant_id), name, CACHE_SECONDS)
    return name or settings.TIME_ZONE


def forget(tenant_id: int) -> None:
    cache.delete(_cache_key(tenant_id))


class TenantTimezoneMiddleware:
    """After TenantResolutionMiddleware: the tenant's zone for the rest of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return self.get_response(request)
        with timezone.override(zone(tenant_zone_name(tenant.id))):
            return self.get_response(request)
