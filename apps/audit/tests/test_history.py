"""The History pages read the payroll system's own tables: every audited model and column has a
name, each record's "History" link shows that record (and its parts) and nothing else."""

import re
from datetime import date
from decimal import Decimal

import pytest

from apps.audit import catalog
from apps.audit.labels import COLUMNS, TABLES
from apps.core.tenancy import tenant_context
from apps.employees.services import employees
from apps.loans.services import loans
from apps.org import services as org
from apps.org.models import Branch
from conftest import login

pytestmark = pytest.mark.django_db
SKIPPED = {"id", "tenant_id", "created_at", "updated_at", "created_by_id", "updated_by_id"}
LINK = re.compile(r'href="(/settings/activity/\?table=(\w+)&amp;row=(\d+))"')


def test_every_audited_model_and_column_has_a_name():
    audited = catalog.audited_models()
    labels = {model._meta.label for model in audited.values()}
    assert labels == set(TABLES), "labels.TABLES must name exactly the audited models"
    unnamed = sorted(f"{model._meta.label}.{field.column}" for model in audited.values()
                     for field in model._meta.concrete_fields
                     if field.column not in SKIPPED and field.column not in COLUMNS)
    assert not unnamed, unnamed


def test_parts_follow_the_models():
    from apps.employees.models import Compensation, Employee, WorkSchedule
    from apps.loans.models import Loan, LoanInstallment
    from apps.mobile.models import AppLinkCode, BiometricEnrollment

    assert set(catalog.parts(Employee)) == {(Compensation, "employee_id"),
                                            (WorkSchedule, "employee_id"),
                                            (BiometricEnrollment, "employee_id"),
                                            (AppLinkCode, "employee_id")}
    assert catalog.parts(Loan) == [(LoanInstallment, "loan_id")]


def _history(client, page: str, table: str):
    html = client.get(page).content.decode()
    found = LINK.search(html)
    assert found, f"no History link on {page}"
    assert found.group(2) == table
    page = client.get(found.group(1).replace("&amp;", "&")).content.decode()
    return " ".join(re.sub(r"<[^>]+>", " ", page).split())  # the words, without the markup


def test_each_history_page_shows_its_own_record(tenant_a, make_employee):
    first = make_employee(tenant_a, 1, name="Mona Adel")
    second = make_employee(tenant_a, 2, name="Karim Fathy")
    with tenant_context(tenant_a.id):
        employees.change_pay(first.pk, employees.CompensationInput(
            effective_from=date(2026, 6, 1), salary=Decimal(7000)))
        loan = loans.grant_loan(loans.LoanInput(
            employee_id=second.pk, granted_on=date(2026, 6, 1), amount=Decimal(1200),
            installments=3, first_month=date(2026, 7, 1)))
        department = org.save_department(org.DepartmentInput(
            branch_id=Branch.objects.get(code=1).pk, code=7, name="Warehouse"))
        branch = Branch.objects.get(code=1)
    client = login(tenant_a, language="en")

    page = _history(client, f"/employees/{first.pk}/", "employees_employee")
    assert "Mona Adel" in page and "Karim Fathy" not in page
    assert "7,000" in page  # the pay change, a part of the employee
    assert "added working hours" in page

    page = _history(client, f"/pay/loans/{loan.pk}/", "loans_loan")
    assert "added loan installment" in page and "Mona Adel" not in page

    page = _history(client, f"/departments/{department.pk}/", "org_department")
    assert "Warehouse" in page and "added employee" not in page

    page = _history(client, f"/branches/{branch.pk}/", "org_branch")
    assert "Mona Adel" not in page


def test_an_unknown_table_shows_nothing(tenant_a, make_employee):
    make_employee(tenant_a, 1, name="Mona Adel")
    client = login(tenant_a, language="en")
    assert "Mona Adel" in client.get("/settings/activity/").content.decode()
    page = client.get("/settings/activity/?table=catalog_currency&row=1").content.decode()
    assert "Mona Adel" not in page and "No changes recorded" in page


def test_no_template_names_a_table():
    from pathlib import Path

    for path in Path("apps").rglob("*.html"):
        assert '_history_link.html" with' not in path.read_text(encoding="utf-8"), path


def test_every_new_record_page_opens(tenant_a):
    """A form for a new record has no history link (nothing saved yet) and must still open."""
    from django.urls import get_resolver

    pages = sorted({f"/{pattern.pattern}" for pattern in get_resolver().url_patterns
                    if str(pattern.pattern).endswith("new/") and "<" not in str(pattern.pattern)})
    assert "/branches/new/" in pages and "/settings/users/new/" in pages
    client = login(tenant_a, language="en")
    for url in pages:
        assert client.get(url).status_code == 200, url


def test_dates_and_times_read_like_the_rest_of_the_page(tenant_a):
    from django.utils import timezone

    from apps.audit.models import AuditEvent

    from ..web.views import _describe

    def shown(table, column, old, new):
        event = AuditEvent(table_name=table, row_id=1, action="U", changes={column: [old, new]})
        change = _describe([event])[0]["changes"][0]
        return change["old"], change["new"]

    with tenant_context(tenant_a.id), timezone.override("Africa/Cairo"):
        # On the client's clock, not UTC, with or without Postgres's trimmed fractions.
        assert shown("messaging_whatsapplink", "linked_at", "2026-10-29T13:20:51.167038+00:00",
                     "2026-10-30T11:33:22.31+00:00") == ("29/10/2026 16:20", "30/10/2026 13:33")
        assert shown("employees_employee", "left_on", None, "2026-03-05") == ("—", "05/03/2026")
        assert shown("employees_workschedule", "starts_at", "09:00:00", "09:30:00") == (
            "09:00", "09:30")
        # Something that is not a date is shown as it is, not lost.
        assert shown("messaging_whatsapplink", "linked_at", "soon", None) == ("soon", "—")
