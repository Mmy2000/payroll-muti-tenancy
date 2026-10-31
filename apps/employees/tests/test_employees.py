"""Employees through the API and the pages: the card, pay and hours history, departures, and
who may see what."""

from datetime import date, time
from decimal import Decimal

import pytest

from apps.core.tenancy import tenant_context
from apps.employees.models import Compensation, Employee
from apps.org.models import Branch
from conftest import login

from ..services import employees

pytestmark = pytest.mark.django_db

API = "/api/web/employees/employees/"


def _payload(branch_id, code=1, name="Ahmed Ali", **extra):
    return {"code": code, "name": name, "branch_id": branch_id, "hired_on": "2025-01-01",
            "national_id": extra.pop("national_id", ""),
            "pay": {"wage_type": "fixed", "pay_frequency": "monthly", "salary": "6000",
                    "hours_per_day": "8",
                    "insured_salary": "5000"},
            "schedule": {"starts_at": "09:00", "ends_at": "17:00", "days_off": [4, 5]},
            **extra}


def _head(tenant):
    with tenant_context(tenant.id):
        return Branch.objects.get(code=1)


def _create(tenant, code=1, branch=None, **extra):
    branch = branch or _head(tenant)
    with tenant_context(tenant.id):
        return employees.create_employee(
            employees.EmployeeInput(code=code, name=f"Employee {code}", branch_id=branch.pk,
                                   hired_on=date(2025, 1, 1), **extra),
            employees.CompensationInput(effective_from=None, salary=Decimal(6000)),
            employees.ScheduleInput(effective_from=None, starts_at=time(9), ends_at=time(17)))


def test_the_owner_adds_an_employee_with_pay_and_hours(tenant_a):
    client = login(tenant_a)
    response = client.post(API, _payload(_head(tenant_a).pk, national_id="29001011234567"),
                           content_type="application/json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["pay"]["salary"] == "6000.00"
    assert body["pay"]["daily_rate"] == "200.000000" and body["pay"]["hourly_rate"] == "25.000000"
    assert body["schedule"]["days_off"] == [4, 5]
    assert body["national_id"] == "29001011234567"
    with tenant_context(tenant_a.id):
        employee = Employee.objects.get()
        # Stored encrypted, never in clear.
        assert "29001011234567" not in employee.national_id_encrypted
        assert employee.national_id == "29001011234567"
        assert employee.pay_history.get().effective_from == date(2025, 1, 1)


def test_errors_point_at_the_fields(tenant_a):
    client = login(tenant_a)
    bad = _payload(_head(tenant_a).pk, national_id="123")
    bad["pay"]["hours_per_day"] = "0"
    bad["schedule"]["ends_at"] = "09:00"
    body = client.post(API, bad, content_type="application/json").json()["error"]
    assert set(body["fields"]) >= {"national_id", "pay.hours_per_day", "schedule.ends_at"}
    with tenant_context(tenant_a.id):
        assert not Employee.objects.exists()  # nothing half-saved


def test_codes_and_national_ids_are_unique(tenant_a, tenant_b):
    client = login(tenant_a)
    first = _payload(_head(tenant_a).pk, national_id="29001011234567")
    assert client.post(API, first, content_type="application/json").status_code == 201
    again = _payload(_head(tenant_a).pk, code=2, national_id="29001011234567")
    fields = client.post(API, again, content_type="application/json").json()["error"]["fields"]
    assert "national_id" in fields
    same_code = _payload(_head(tenant_a).pk, code=1, name="Other")
    assert "code" in client.post(API, same_code,
                                 content_type="application/json").json()["error"]["fields"]
    # Another client may use the same code and national ID.
    other = login(tenant_b).post(API, _payload(_head(tenant_b).pk, national_id="29001011234567"),
                                 content_type="application/json")
    assert other.status_code == 201


def test_pay_is_hidden_from_members_without_the_salary_permission(tenant_a, make_member):
    employee = _create(tenant_a)
    make_member(tenant_a, "val", "viewer")
    viewer = login(tenant_a, "val")
    body = viewer.get(f"{API}{employee.pk}/").json()
    assert body["name"] == "Employee 1" and "pay" not in body and "national_id" not in body
    page = viewer.get(f"/employees/{employee.pk}/").content.decode()
    assert "6,000.00" not in page and "Change pay" not in page
    assert viewer.post(f"{API}{employee.pk}/pay/", {"effective_from": "2025-06-01",
                                                    "salary": "9000"},
                       content_type="application/json").status_code == 403


def test_branch_scoped_members_see_only_their_branch(tenant_a, make_member):
    with tenant_context(tenant_a.id):
        second = Branch.objects.create(code=2, name="Alexandria")
    _create(tenant_a, code=1)
    there = _create(tenant_a, code=2, branch=second)
    make_member(tenant_a, "mona", "manager", branches=[second])
    manager = login(tenant_a, "mona")
    listed = manager.get(API).json()["results"]
    assert [row["code"] for row in listed] == [2]
    with tenant_context(tenant_a.id):
        head_id = Employee.objects.get(code=1).pk
    assert manager.get(f"{API}{head_id}/").status_code == 404
    assert manager.get(f"/employees/{head_id}/").status_code == 404
    # Can't move an employee into a branch they don't manage.
    card = _payload(_head(tenant_a).pk, code=2, name="Moved")
    del card["pay"], card["schedule"]
    assert manager.put(f"{API}{there.pk}/", card,
                       content_type="application/json").status_code == 403


def test_pay_changes_keep_their_history(tenant_a):
    employee = _create(tenant_a)
    client = login(tenant_a)
    raise_ = {"effective_from": "2025-07-01", "salary": "7500", "note": "Yearly raise"}
    body = client.post(f"{API}{employee.pk}/pay/", raise_,
                       content_type="application/json").json()
    assert body["pay"]["salary"] == "7500.00"  # in effect today
    with tenant_context(tenant_a.id):
        from apps.core.history import in_effect

        rows = Compensation.objects.filter(employee=employee)
        assert in_effect(rows, date(2025, 6, 30)).salary == 6000
        assert in_effect(rows, date(2025, 7, 1)).salary == 7500
        first, later = rows.order_by("effective_from")
    # The same date twice, or before hiring, is refused.
    again = client.post(f"{API}{employee.pk}/pay/", raise_, content_type="application/json")
    assert "effective_from" in again.json()["error"]["fields"]
    early = client.post(f"{API}{employee.pk}/pay/", {**raise_, "effective_from": "2024-01-01"},
                        content_type="application/json")
    assert "effective_from" in early.json()["error"]["fields"]
    # A change can be removed; the starting pay can't.
    blocked = client.delete(f"/api/web/employees/pay-changes/{first.pk}/")
    assert blocked.json()["error"]["code"] == "EMPLOYEES_FIRST_RECORD"
    assert client.delete(f"/api/web/employees/pay-changes/{later.pk}/").status_code == 204


def test_hours_change_from_a_date(tenant_a):
    employee = _create(tenant_a)
    client = login(tenant_a)
    response = client.post(f"{API}{employee.pk}/schedule/", {
        "effective_from": "2025-03-01", "starts_at": "22:00", "ends_at": "06:00",
        "days_off": [4]}, content_type="application/json")
    assert response.status_code == 200, response.content
    with tenant_context(tenant_a.id):
        assert employee.schedules.count() == 2
    all_week = client.post(f"{API}{employee.pk}/schedule/", {
        "effective_from": "2025-04-01", "starts_at": "09:00", "ends_at": "17:00",
        "days_off": [0, 1, 2, 3, 4, 5, 6]}, content_type="application/json")
    assert "days_off" in all_week.json()["error"]["fields"]


def test_ending_and_restoring_employment(tenant_a):
    employee = _create(tenant_a)
    client = login(tenant_a)
    before = client.post(f"{API}{employee.pk}/leave/", {"left_on": "2024-12-31"},
                         content_type="application/json")
    assert "left_on" in before.json()["error"]["fields"]
    body = client.post(f"{API}{employee.pk}/leave/", {"left_on": "2025-05-31",
                                                      "reason": "Resigned"},
                       content_type="application/json").json()
    assert body["left_on"] == "2025-05-31" and body["is_active"] is False
    # Left employees are out of the default list, and back with "All".
    assert "Employee 1" not in client.get("/employees/").content.decode()
    assert "Employee 1" in client.get("/employees/?status=all").content.decode()
    after = client.post(f"{API}{employee.pk}/pay/", {"effective_from": "2025-06-01",
                                                     "salary": "1"},
                        content_type="application/json")
    assert "effective_from" in after.json()["error"]["fields"]
    assert client.post(f"{API}{employee.pk}/reinstate/").json()["left_on"] is None


def test_pages_render(tenant_a):
    employee = _create(tenant_a)
    client = login(tenant_a, language="en")
    for path in ("/employees/", "/employees/new/", f"/employees/{employee.pk}/",
                 f"/employees/{employee.pk}/edit/", "/employees/import/", "/departments/",
                 "/departments/new/"):
        assert client.get(path).status_code == 200, path
    page = client.get(f"/employees/{employee.pk}/").content.decode()
    assert "6,000.00" in page and "200.00" in page  # salary and daily rate
    listed = client.get("/employees/?q=Employee").content.decode()
    assert f'href="/employees/{employee.pk}/"' in listed
