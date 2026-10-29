"""The payroll API and pages: the workflow through the browser's endpoints, and who sees what."""

import pytest

from apps.core.tenancy import tenant_context
from apps.org.models import Branch
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from conftest import login

RUNS = "/api/web/payroll/runs/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def client_a(tenant_a):
    TenantFeature.objects.create(tenant=tenant_a, key="attendance", enabled=False)
    features.forget(tenant_a.pk)
    return tenant_a


def _post(client, url, body=None):
    return client.post(url, body or {}, content_type="application/json")


def test_a_run_through_the_api_and_its_pages(client_a, make_employee):
    employee = make_employee(client_a)
    client = login(client_a, language="en")
    created = _post(client, RUNS, {"frequency": "monthly", "day": "2026-10-15"})
    assert created.status_code == 201, created.content
    run = created.json()
    assert (run["start"], run["end"], run["net"]) == ("2026-10-01", "2026-10-31", "6000.00")
    slip = client.get(f"/api/web/payroll/payslips/?run={run['id']}").json()["results"][0]
    assert slip["lines"][0]["title"] == "Salary"

    line = _post(client, f"{RUNS}{run['id']}/lines/",
                 {"employee_id": employee.pk, "label": "Bonus", "amount": "100",
                  "addition": "false"})
    assert line.status_code == 201 and line.json()["net"] == "5900.00"
    assert line.json()["id"] == slip["id"]  # recalculated in place
    manual = client.get(f"/payroll/{run['id']}/payslips/{slip['id']}/").content.decode()
    assert "Bonus" in manual and "Lines added by hand" in manual

    for path in ("/payroll/", "/payroll/new/", f"/payroll/{run['id']}/",
                 "/pay-setup/calendars/"):
        assert client.get(path).status_code == 200, path
    assert _post(client, f"{RUNS}{run['id']}/approve/").json()["status"] == "approved"
    paid = _post(client, f"{RUNS}{run['id']}/pay/", {"paid_on": "2026-11-01", "method": "Bank"})
    assert paid.json()["status"] == "paid"
    refused = _post(client, f"{RUNS}{run['id']}/reverse/", {"reason": "late"})
    assert refused.status_code == 409


def test_off_cycle_needs_dates_and_a_reason(client_a, make_employee):
    make_employee(client_a)
    client = login(client_a)
    refused = _post(client, RUNS, {"frequency": "monthly", "kind": "off_cycle",
                                   "start": "2026-10-01", "end": "2026-10-31"})
    assert refused.status_code == 400 and "reason" in refused.json()["error"]["fields"]


def test_calendars_are_set_up_once(client_a, make_employee):
    make_employee(client_a)
    client = login(client_a)
    saved = client.put("/api/web/payroll/calendars/monthly/", {"start_day": 26},
                       content_type="application/json")
    assert saved.json()["start_day"] == 26
    run = _post(client, RUNS, {"frequency": "monthly", "day": "2026-10-15"}).json()
    assert (run["start"], run["end"]) == ("2026-09-26", "2026-10-25")
    moved = client.put("/api/web/payroll/calendars/monthly/", {"start_day": 1},
                       content_type="application/json")
    assert moved.status_code == 422
    assert moved.json()["error"]["code"] == "PAYROLL_CALENDAR_IN_USE"


def test_a_branch_manager_runs_their_branch_only(client_a, make_employee, make_member):
    with tenant_context(client_a.id):
        other = Branch.objects.create(code=2, name="Alexandria")
    make_employee(client_a, 1)
    make_employee(client_a, 2, branch=other)
    make_member(client_a, "mona", "manager", branches=[other])
    manager = login(client_a, "mona")
    everyone = _post(manager, RUNS, {"frequency": "monthly", "day": "2026-10-15"})
    assert everyone.status_code == 403
    mine = _post(manager, RUNS, {"frequency": "monthly", "day": "2026-10-15",
                                 "scope": "branch", "scope_id": other.pk})
    assert mine.status_code == 201 and mine.json()["net"] == "6000.00"
    owner_run = _post(login(client_a), RUNS, {"frequency": "monthly", "kind": "off_cycle",
                                              "start": "2026-10-01", "end": "2026-10-31",
                                              "reason": "Bonus"}).json()
    listed = {r["id"] for r in manager.get(RUNS).json()["results"]}
    assert listed == {mine.json()["id"]}
    assert manager.get(f"/payroll/{owner_run['id']}/").status_code == 404
    calendar = manager.put("/api/web/payroll/calendars/weekly/", {"anchor": "2026-01-04"},
                           content_type="application/json")
    assert calendar.status_code == 403  # the whole company's calendar


def test_a_viewer_doesnt_see_pay(client_a, make_member):
    make_member(client_a, "val", "viewer")
    viewer = login(client_a, "val")
    assert viewer.get(RUNS).status_code == 403
    assert viewer.get("/payroll/").status_code in (302, 403)
