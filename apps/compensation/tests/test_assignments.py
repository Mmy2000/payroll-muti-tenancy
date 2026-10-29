"""Giving pay items to employees on a schedule."""

from datetime import date

import pytest

from apps.compensation.models import PayItem, PayItemAssignment
from apps.core import locks
from apps.core.tenancy import tenant_context
from apps.org.models import Branch
from conftest import login

pytestmark = pytest.mark.django_db

API = "/api/web/compensation/assignments/"


def _item(tenant, basis="fixed"):
    with tenant_context(tenant.id):
        return PayItem.objects.create(code=1, name="Transport", kind="addition", basis=basis).pk


def _give(client, item, target_kind, target_id, frequency="monthly", starts="2026-10-01",
          ends=None, amount="300"):
    return client.post(API, {"item_id": item, "target_kind": target_kind,
                             "target_id": target_id, "frequency": frequency,
                             "starts_on": starts, "ends_on": ends, "amount": amount},
                       content_type="application/json")


def test_a_branch_gets_one_assignment_each(tenant_a, make_employee):
    make_employee(tenant_a, 1)
    make_employee(tenant_a, 2)
    with tenant_context(tenant_a.id):
        head = Branch.objects.get(code=1).pk
    response = _give(login(tenant_a), _item(tenant_a), "branch", head, ends="2026-12-31")
    assert response.json() == {"created": 2}
    with tenant_context(tenant_a.id):
        assert set(PayItemAssignment.objects.values_list("ends_on", flat=True)) == {
            date(2026, 12, 31)}


def test_the_same_item_cant_run_twice_over_the_same_days(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    item = _item(tenant_a)
    client = login(tenant_a)
    assert _give(client, item, "employee", employee.pk, ends="2026-11-30").status_code == 201
    clash = _give(client, item, "employee", employee.pk, starts="2026-11-15")
    assert "starts_on" in clash.json()["error"]["fields"]
    after = _give(client, item, "employee", employee.pk, starts="2026-12-01")
    assert after.status_code == 201  # open-ended, after the first one ends


def test_a_one_time_item_is_on_its_day(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    _give(login(tenant_a), _item(tenant_a), "employee", employee.pk, "once", "2026-10-15",
          ends="2027-01-01")
    with tenant_context(tenant_a.id):
        row = PayItemAssignment.objects.get()
        assert row.ends_on == date(2026, 10, 15)


def test_ending_and_cancelling(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    _give(client, _item(tenant_a), "employee", employee.pk)
    with tenant_context(tenant_a.id):
        pk = PayItemAssignment.objects.get().pk
    ended = client.post(f"{API}{pk}/end/", {"ends_on": "2027-03-31"},
                        content_type="application/json")
    assert ended.json()["ends_on"] == "2027-03-31"
    assert client.post(f"{API}{pk}/cancel/").json() == {"cancelled": 1}
    assert client.post(f"{API}{pk}/cancel/").json()["error"]["code"] == "COMPENSATION_ENTRY_STATE"


def test_what_payroll_paid_cant_be_cancelled(tenant_a, make_employee, monkeypatch):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    _give(client, _item(tenant_a), "employee", employee.pk)
    with tenant_context(tenant_a.id):
        pk = PayItemAssignment.objects.get().pk
    monkeypatch.setattr(locks, "_source_checks", [lambda label, object_id: object_id == pk])
    refused = client.post(f"{API}{pk}/cancel/")
    assert refused.json()["error"]["code"] == "PAYROLL_LOCKED"


def test_pages_render_and_keep_the_month(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    _give(login(tenant_a), _item(tenant_a), "employee", employee.pk, starts="2026-12-01",
          ends="2026-12-31")
    client = login(tenant_a, language="en")
    december = client.get("/pay/items/?month=2026-12").content.decode()
    assert "Nothing given this month" not in december
    assert 'name="month" value="2026-12"' in december  # the filters keep the month
    assert "Nothing given this month" in client.get("/pay/items/?month=2026-11").content.decode()
    assert client.get("/pay/items/new/").status_code == 200
