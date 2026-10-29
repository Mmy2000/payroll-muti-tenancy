"""Advances and loans: the rules, through the API."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.core.months import add_months, months, parse
from apps.core.tenancy import tenant_context
from apps.loans.domain.installments import split
from apps.loans.models import InstallmentStatus, Loan, LoanInstallment
from conftest import login

LOANS = "/api/web/loans/loans/"
ADVANCES = "/api/web/loans/advances/"


def test_installments_add_up_to_the_loan():
    assert split(D(1000), 3) == [D("333.33"), D("333.33"), D("333.34")]
    assert split(D(1200), 12) == [D(100)] * 12
    assert sum(split(D("999.99"), 7)) == D("999.99")


def test_months():
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert months(date(2026, 12, 15), 2) == [date(2026, 12, 1), date(2027, 1, 1)]
    assert parse("2026-02", date(2000, 1, 1)) == date(2026, 2, 1)
    assert parse("nonsense", date(2026, 5, 9)) == date(2026, 5, 1)


def _loan(client, employee, amount="1000", count=3, first="2026-11"):
    return client.post(LOANS, {"employee_id": employee.pk, "granted_on": "2026-10-20",
                               "amount": amount, "installments": count, "first_month": first},
                       content_type="application/json")


@pytest.mark.django_db
def test_a_loan_and_its_installments(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    response = _loan(login(tenant_a), employee)
    assert response.status_code == 201, response.content
    rows = response.json()["installments"]
    assert [(r["due_month"], r["amount"]) for r in rows] == [
        ("2026-11-01", "333.33"), ("2026-12-01", "333.33"), ("2027-01-01", "333.34")]


@pytest.mark.django_db
def test_one_loan_at_a_time_and_sensible_dates(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    assert _loan(client, employee).status_code == 201
    again = _loan(client, employee)
    assert again.json()["error"]["code"] == "LOANS_ONE_AT_A_TIME"
    other = make_employee(tenant_a, 2)
    early = _loan(client, other, first="2026-09")
    assert "first_month" in early.json()["error"]["fields"]
    tiny = _loan(client, other, amount="0.05", count=12)  # less than a piastre each
    assert "amount" in tiny.json()["error"]["fields"]


@pytest.mark.django_db
def test_postponing_moves_the_rest_a_month_on(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    loan = _loan(client, employee).json()
    second = loan["installments"][1]["id"]
    moved = client.post(f"/api/web/loans/installments/{second}/postpone/").json()
    assert [r["due_month"] for r in moved["installments"]] == [
        "2026-11-01", "2027-01-01", "2027-02-01"]


@pytest.mark.django_db
def test_a_loan_is_cancelled_only_before_it_is_paid_from(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    loan = _loan(client, employee).json()
    with tenant_context(tenant_a.id):  # what payroll will do (phase 4)
        LoanInstallment.objects.filter(pk=loan["installments"][0]["id"]).update(
            status=InstallmentStatus.PAID)
    refused = client.post(f"{LOANS}{loan['id']}/cancel/")
    assert refused.json()["error"]["code"] == "LOANS_LOAN_PARTLY_PAID"
    fresh = _loan(client, make_employee(tenant_a, 2)).json()
    assert client.post(f"{LOANS}{fresh['id']}/cancel/").json()["status"] == "cancelled"
    with tenant_context(tenant_a.id):
        assert set(Loan.objects.get(pk=fresh["id"]).installments.values_list(
            "status", flat=True)) == {InstallmentStatus.CANCELLED}


@pytest.mark.django_db
def test_a_months_advances_stay_within_a_months_pay(tenant_a, make_employee):
    monthly = make_employee(tenant_a, salary=D(6000))
    daily = make_employee(tenant_a, 2, salary=D(200))
    with tenant_context(tenant_a.id):
        pay = daily.pay_history.get()
        pay.wage_type = "daily"
        pay.save()
    client = login(tenant_a)

    def give(employee, amount, day="2026-10-05"):
        return client.post(ADVANCES, {"employee_id": employee.pk, "date": day, "amount": amount},
                           content_type="application/json")

    assert give(monthly, "4000").status_code == 201
    assert give(monthly, "2500").json()["error"]["code"] == "LOANS_ADVANCE_LIMIT"
    assert give(monthly, "2500", "2026-11-02").status_code == 201  # another month
    assert give(daily, "6000").status_code == 201  # 30 days × 200
    assert give(daily, "1").json()["error"]["code"] == "LOANS_ADVANCE_LIMIT"
    first = client.get(f"{ADVANCES}?employee={monthly.pk}").json()["results"][-1]
    assert client.post(f"{ADVANCES}{first['id']}/cancel/").json()["status"] == "cancelled"
    assert give(monthly, "2500").status_code == 201  # the cancelled one no longer counts


@pytest.mark.django_db
def test_pages_render(tenant_a, make_employee):
    loan = _loan(login(tenant_a), make_employee(tenant_a)).json()
    client = login(tenant_a, language="en")
    for path in ("/pay/advances/", "/pay/loans/", "/pay/loans/new/", f"/pay/loans/{loan['id']}/"):
        assert client.get(path).status_code == 200, path
    assert "333.34" in client.get(f"/pay/loans/{loan['id']}/").content.decode()
