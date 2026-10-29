"""Setting up pay policies and pay items through the API, and their feature switches."""

import pytest

from apps.core.tenancy import tenant_context
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from apps.policies.models import LatenessPolicy, TaxTable
from conftest import login

pytestmark = pytest.mark.django_db


def _post(client, url, data, method="post"):
    return getattr(client, method)(url, data, content_type="application/json")


def test_a_lateness_policy_with_bands(tenant_a):
    client = login(tenant_a)
    created = _post(client, "/api/web/policies/lateness/", {
        "name": "Standard", "minutes": 10,
        "bands": [{"from_minutes": 31, "to_minutes": 60, "hours": "2"},
                  {"from_minutes": 11, "to_minutes": 30, "hours": "1"}]})
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["grace_minutes"] == 10
    assert [b["from_minutes"] for b in body["bands"]] == [11, 31]  # stored in order
    # Saving replaces the bands.
    updated = _post(client, f"/api/web/policies/lateness/{body['id']}/", {
        "name": "Standard", "minutes": 5, "bands": []}, "put").json()
    assert updated["bands"] == [] and updated["grace_minutes"] == 5


def test_overlapping_bands_are_refused_with_the_row(tenant_a):
    response = _post(login(tenant_a), "/api/web/policies/overtime/", {
        "name": "Shift", "bands": [{"from_minutes": 0, "to_minutes": 60, "hours": "1"},
                                   {"from_minutes": 30, "to_minutes": 90, "hours": "2"}]})
    assert response.status_code == 400
    assert "1" in response.json()["error"]["fields"]["bands"]
    with tenant_context(tenant_a.id):
        assert not LatenessPolicy.objects.exists()


def test_policy_names_are_unique(tenant_a):
    client = login(tenant_a)
    assert _post(client, "/api/web/policies/lateness/", {"name": "A"}).status_code == 201
    again = _post(client, "/api/web/policies/lateness/", {"name": "A"})
    assert "name" in again.json()["error"]["fields"]


def test_tax_tables(tenant_a):
    client = login(tenant_a)
    table = {"effective_from": "2025-01-01", "annual_exemption": "20000",
             "brackets": [{"up_to": "40000", "rate": "0"}, {"up_to": None, "rate": "10"}]}
    created = _post(client, "/api/web/policies/tax-tables/", table)
    assert created.status_code == 201, created.content
    assert created.json()["brackets"][1] == {"up_to": None, "rate": "10.000"}
    # Two tables can't start the same day; open brackets go last.
    assert "effective_from" in _post(client, "/api/web/policies/tax-tables/",
                                     table).json()["error"]["fields"]
    wrong = {**table, "effective_from": "2026-01-01",
             "brackets": [{"up_to": None, "rate": "0"}, {"up_to": "5", "rate": "1"}]}
    assert "brackets" in _post(client, "/api/web/policies/tax-tables/",
                               wrong).json()["error"]["fields"]
    assert client.delete(f"/api/web/policies/tax-tables/{created.json()['id']}/"
                         ).status_code == 204
    with tenant_context(tenant_a.id):
        assert not TaxTable.objects.exists()


def test_insurance_rates_and_holidays(tenant_a):
    client = login(tenant_a)
    rate = _post(client, "/api/web/policies/insurance-rates/", {
        "effective_from": "2025-01-01", "employee_rate": "11", "employer_rate": "18.75",
        "min_insured": "2000", "max_insured": "1000"})
    assert "max_insured" in rate.json()["error"]["fields"]
    holiday = {"date": "2025-10-06", "name": "Armed Forces Day", "branch_id": None}
    assert _post(client, "/api/web/policies/holidays/", holiday).status_code == 201
    assert "date" in _post(client, "/api/web/policies/holidays/",
                           holiday).json()["error"]["fields"]


def test_pay_items(tenant_a):
    client = login(tenant_a)
    item = {"code": 1, "name": "Transport", "kind": "addition", "basis": "per_day",
            "taxable": True}
    created = _post(client, "/api/web/compensation/items/", item)
    assert created.status_code == 201 and created.json()["basis"] == "per_day"
    assert "code" in _post(client, "/api/web/compensation/items/",
                           {**item, "name": "Meals"}).json()["error"]["fields"]


def test_viewers_read_but_do_not_change(tenant_a, make_member):
    make_member(tenant_a, "val", "viewer")
    viewer = login(tenant_a, "val")
    assert viewer.get("/api/web/policies/lateness/").status_code == 200
    assert _post(viewer, "/api/web/policies/lateness/", {"name": "X"}).status_code == 403
    assert viewer.get("/pay-setup/lateness/new/").status_code == 403


def test_pages_render(tenant_a):
    client = login(tenant_a, language="en")
    lateness = _post(client, "/api/web/policies/lateness/", {
        "name": "Std", "bands": [{"from_minutes": 1, "to_minutes": 9, "hours": "1"}]}).json()
    table = _post(client, "/api/web/policies/tax-tables/", {
        "effective_from": "2025-01-01", "brackets": [{"up_to": None, "rate": "10"}]}).json()
    for path in ("/pay-setup/items/", "/pay-setup/items/new/", "/pay-setup/lateness/",
                 "/pay-setup/lateness/new/", f"/pay-setup/lateness/{lateness['id']}/",
                 "/pay-setup/overtime/", "/pay-setup/overtime/new/", "/pay-setup/tax/",
                 "/pay-setup/tax/new/", f"/pay-setup/tax/{table['id']}/",
                 "/pay-setup/insurance/", "/pay-setup/insurance/new/", "/pay-setup/holidays/"):
        assert client.get(path).status_code == 200, path


def test_switching_a_policy_feature_off(tenant_a, tenant_b):
    TenantFeature.objects.create(tenant=tenant_a, key="lateness", enabled=False)
    features.forget(tenant_a.pk)
    owner = login(tenant_a)
    assert 'href="/pay-setup/lateness/"' not in owner.get("/").content.decode()
    assert owner.get("/pay-setup/lateness/").status_code == 403
    assert owner.get("/api/web/policies/lateness/").status_code == 403
    assert owner.get("/pay-setup/overtime/").status_code == 200  # others stay on
    assert login(tenant_b).get("/pay-setup/lateness/").status_code == 200
