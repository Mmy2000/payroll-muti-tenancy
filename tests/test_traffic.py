"""Client traffic: counting, the requests-per-minute limit, and the console's Traffic pages."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.platform.tenants import traffic
from apps.platform.tenants.models import (
    TenantRouteTraffic,
    TenantTraffic,
)
from conftest import login

pytestmark = pytest.mark.django_db
HOST = "admin.localhost"


def _minute(tenant):
    return TenantTraffic.objects.get(tenant=tenant, minute=traffic.current_minute())


def test_requests_are_counted_per_client_and_route(tenant_a, tenant_b):
    client = login(tenant_a)  # the login POST counts too
    assert client.get("/").status_code == 200
    row = _minute(tenant_a)
    assert (row.requests, row.throttled, row.errors) == (2, 0, 0)
    assert row.total_ms >= row.max_ms >= 0
    routes = set(TenantRouteTraffic.objects.filter(tenant=tenant_a)
                 .values_list("route", flat=True))
    assert {"POST /login/", "GET /"} <= routes
    assert not TenantTraffic.objects.filter(tenant=tenant_b).exists()


def test_over_the_limit_the_workspace_answers_429(tenant_a):
    tenant_a.requests_per_minute = 3
    tenant_a.save()
    client = login(tenant_a)  # 1
    assert client.get("/").status_code == 200  # 2
    assert client.get("/").status_code == 200  # 3
    refused = client.get("/")
    assert refused.status_code == 429 and 1 <= int(refused["Retry-After"]) <= 60
    api = client.get("/api/web/branches/")
    assert api.status_code == 429 and api.json()["error"]["code"] == "THROTTLED"
    row = _minute(tenant_a)
    assert (row.requests, row.throttled) == (5, 2)


def test_platform_default_and_no_limit(tenant_a, settings):
    settings.TENANT_REQUESTS_PER_MINUTE = 1
    assert traffic.limit_for(tenant_a) == 1
    client = login(tenant_a)
    assert client.get("/").status_code == 429
    tenant_a.requests_per_minute = 0  # this client: no limit
    tenant_a.save()
    assert traffic.limit_for(tenant_a) is None
    assert client.get("/").status_code == 200
    settings.TENANT_REQUESTS_PER_MINUTE = 0
    tenant_a.requests_per_minute = None
    assert traffic.limit_for(tenant_a) is None


def test_prune_traffic(tenant_a):
    old = timezone.now() - timedelta(days=40)
    traffic.record(tenant_a.id, traffic.current_minute(old), route="GET /", ms=5)
    traffic.record(tenant_a.id, traffic.current_minute(), route="GET /", ms=5)
    out = StringIO()
    call_command("prune_traffic", stdout=out)
    assert "deleted 1 minute rows, 0 route rows" in out.getvalue()
    assert TenantTraffic.objects.count() == 1
    assert TenantRouteTraffic.objects.count() == 2  # routes are kept 90 days
