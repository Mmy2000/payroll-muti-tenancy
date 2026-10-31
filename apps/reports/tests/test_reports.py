"""Reports: the registry's rules, every report on screen and exported, who may read and export
them, and payslips as PDF."""

import io
import re
from datetime import date
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from apps.adjustments.models import AdjustmentType
from apps.adjustments.services import batches as adjustments
from apps.core.tenancy import tenant_context
from apps.employees.selectors import Target
from apps.loans.services import loans
from apps.org.models import Branch
from apps.payroll.services import lifecycle as payroll_lifecycle
from apps.payroll.services import runs as payroll
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from apps.printing import pdf
from apps.reports.catalog.payroll import register_column
from apps.reports.registry import REPORTS, Column, Table
from apps.reports.templatetags.reports import minutes
from conftest import login

pytestmark = pytest.mark.django_db
OCTOBER = "date_from=2026-10-01&date_to=2026-10-31"


@pytest.fixture(scope="module")
def chromium():
    try:
        pdf.html_to_pdf("<p>ok</p>")
    except pdf.PdfUnavailable:
        pytest.skip("Chromium is not installed (python -m playwright install chromium)")


def _switch_off(tenant, *keys):
    for key in keys:
        TenantFeature.objects.create(tenant=tenant, key=key, enabled=False)
    features.forget(tenant.pk)


@pytest.fixture
def paid_october(tenant_a, make_employee):
    """Two employees paid for October (attendance off: fixed salaries), with an incentive, an
    advance and a loan."""
    _switch_off(tenant_a, "attendance")
    first = make_employee(tenant_a, 1, name="Mona Adel", salary=D(6000))
    make_employee(tenant_a, 2, name="Karim Fathy", salary=D(3000))
    with tenant_context(tenant_a.id):
        adjustments.give(adjustments.AdjustmentInput(
            type_id=AdjustmentType.objects.filter(kind="incentive").first().pk,
            target=Target.employee(first.pk), date=date(2026, 10, 10), method="fixed",
            quantity=D(500)), approve=True)
        loans.grant_loan(loans.LoanInput(employee_id=first.pk, granted_on=date(2026, 9, 20),
                                         amount=D(1200), installments=3,
                                         first_month=date(2026, 10, 1)))
        run = payroll.create_run(payroll.RunInput(frequency="monthly", day=date(2026, 10, 15)))
        payroll_lifecycle.approve_run(run.pk)
    return run


# --- the rules ---------------------------------------------------------------------------------


def test_payslip_lines_fall_in_register_columns():
    assert register_column("salary", "earning") == "pay"
    assert register_column("overtime", "earning") == "extra"
    assert register_column("penalty", "earning") == "other_plus"  # a penalty given back
    assert register_column("penalty", "deduction") == "penalties"
    assert register_column("item", "deduction") == "items_minus"
    assert register_column("manual", "deduction") == "other_minus"
    assert register_column("insurance_employer", "employer") is None


def test_totals_and_minutes():
    table = Table("t", [Column("name", "Name"), Column("pay", "Pay", "money"),
                        Column("late", "Late", "minutes"), Column("rate", "Rate", "pct")],
                  [{"name": "a", "pay": D("10.50"), "late": 65, "rate": D(5)},
                   {"name": "b", "pay": D(2), "late": 10, "rate": D(7)}])
    assert table.add_totals("name", "Total").totals == {"name": "Total", "pay": D("12.50"),
                                                        "late": 75}
    assert (minutes(75), minutes(0), minutes(None), minutes(-5)) == ("1:15", "0:00", "", "-0:05")


def test_a_range_is_put_in_order_and_kept_short(tenant_a, make_employee):
    client = login(tenant_a, language="en")
    page = client.get("/reports/daily_attendance/?date_from=2026-10-31&date_to=2026-08-01")
    assert page.status_code == 200
    html = page.content.decode()
    assert 'value="2026-10-01"' in html and 'value="2026-10-31"' in html  # swapped, 31 days


# --- every report ------------------------------------------------------------------------------


def test_every_report_shows_and_exports(paid_october, tenant_a):
    client = login(tenant_a, language="en")
    index = client.get("/reports/").content.decode()
    for code, report in REPORTS.items():
        if report.section == "attendance":
            continue  # attendance (and leave with it) is off for these fixed salaries
        assert f"/reports/{code}/" in index, code
        page = client.get(f"/reports/{code}/?{OCTOBER}")
        assert page.status_code == 200, code
        book = client.get(f"/reports/{code}/?{OCTOBER}&format=xlsx")
        assert book.status_code == 200, code
        assert book["Content-Disposition"].startswith("attachment")
        load_workbook(io.BytesIO(book.content))  # a real workbook


def test_the_register_adds_up_the_frozen_payslips(paid_october, tenant_a):
    client = login(tenant_a, language="en")
    page = client.get(f"/reports/payroll_register/?{OCTOBER}").content.decode()
    assert "Mona Adel" in page and "Karim Fathy" in page
    book = load_workbook(io.BytesIO(client.get(
        f"/reports/payroll_register/?{OCTOBER}&format=xlsx").content))
    sheet = book.active
    rows = [[cell.value for cell in row] for row in sheet.iter_rows()]
    header = next(row for row in rows if row and row[0] == "Code")
    total = next(row for row in rows if row and row[1] == "Total")
    column = {name: index for index, name in enumerate(header)}
    assert total[column["Salary or wages"]] == 9000.0
    assert total[column["Incentives"]] == 500.0
    assert total[column["Loan installments"]] == 400.0
    assert total[column["Net"]] == 9100.0
    cell = sheet.cell(row=rows.index(total) + 1, column=column["Net"] + 1)
    assert cell.number_format == "#,##0.00" and not sheet.sheet_view.rightToLeft

    drafts = client.get(f"/reports/payroll_register/?{OCTOBER}&runs=draft").content.decode()
    assert "/payslips/" not in drafts and "/payslips/" in page  # approved runs only


def test_an_arabic_workbook_reads_right_to_left(paid_october, tenant_a):
    client = login(tenant_a, language="ar")
    book = load_workbook(io.BytesIO(client.get(
        "/reports/loan_balances/?date_from=2026-09-01&date_to=2026-10-31&format=xlsx").content))
    assert book.active.sheet_view.rightToLeft


def test_reports_and_payslips_as_pdf(chromium, paid_october, tenant_a):
    client = login(tenant_a, language="ar")
    report = client.get(f"/reports/payroll_register/?{OCTOBER}&format=pdf")
    assert report.status_code == 200 and report.content.startswith(b"%PDF-")
    width, height = (float(v) for v in re.search(
        rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", report.content).groups())
    assert width > height  # a wide register goes sideways
    slips = client.get(f"/payroll/{paid_october.pk}/payslips.pdf")
    assert slips.status_code == 200 and slips.content.startswith(b"%PDF-")
    assert slips.content.count(b"/Type /Page\n") + slips.content.count(b"/Type/Page") >= 1
    with tenant_context(tenant_a.id):
        slip = paid_october.payslips.first()
    one = client.get(f"/payroll/{paid_october.pk}/payslips/{slip.pk}/pdf/?inline=1")
    assert one.status_code == 200 and one["Content-Disposition"].startswith("inline")


def test_without_chromium_the_page_says_so(paid_october, tenant_a, monkeypatch):
    def broken(*args, **kwargs):
        raise pdf.PdfUnavailable("no browser")

    monkeypatch.setattr(pdf, "html_to_pdf", broken)
    client = login(tenant_a, language="en")
    response = client.get(f"/reports/payroll_register/?{OCTOBER}&format=pdf")
    assert response.status_code == 503 and b"Save as PDF" in response.content
    assert client.get(f"/payroll/{paid_october.pk}/payslips.pdf").status_code == 503


# --- who may read and export -------------------------------------------------------------------


def test_reports_follow_the_data_permissions(paid_october, tenant_a, tenant_b, make_member):
    make_member(tenant_a, "viewer", "viewer")
    viewer = login(tenant_a, "viewer", language="en")
    assert viewer.get(f"/reports/payroll_register/?{OCTOBER}").status_code == 403  # pay
    employees = viewer.get("/reports/employee_list/")
    assert employees.status_code == 200
    assert "Salary or wage" not in employees.content.decode()  # no pay permission
    assert "format=xlsx" not in employees.content.decode()  # no export permission
    assert viewer.get("/reports/employee_list/?format=xlsx").status_code == 403
    assert "/reports/payroll_register/" not in viewer.get("/reports/").content.decode()

    assert login(tenant_b).get(f"/reports/payroll_register/?{OCTOBER}").status_code == 200
    other = login(tenant_b, language="en").get("/reports/employee_list/")
    assert "Mona Adel" not in other.content.decode()  # another client's people
    assert login(tenant_a).get("/reports/nope/").status_code == 404


def test_a_branch_manager_reads_their_branch_only(paid_october, tenant_a, make_employee,
                                                  make_member):
    with tenant_context(tenant_a.id):
        alexandria = Branch.objects.create(code=2, name="Alexandria")
    make_employee(tenant_a, 3, name="Hala Samir", branch=alexandria)
    make_member(tenant_a, "alex", "manager", branches=[alexandria])
    page = login(tenant_a, "alex", language="en").get("/reports/employee_list/").content.decode()
    assert "Hala Samir" in page and "Mona Adel" not in page


def test_features_switch_reports_and_export_off(paid_october, tenant_a):
    client = login(tenant_a, language="en")
    assert client.get("/reports/daily_attendance/").status_code == 403  # attendance is off
    assert "/reports/daily_attendance/" not in client.get("/reports/").content.decode()
    _switch_off(tenant_a, "reports_export")
    page = client.get(f"/reports/payroll_register/?{OCTOBER}")
    assert page.status_code == 200 and "format=pdf" not in page.content.decode()
    assert client.get(f"/reports/payroll_register/?{OCTOBER}&format=xlsx").status_code == 403
