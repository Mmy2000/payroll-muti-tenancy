"""Phase 7: evaluations and their card, the notifications bell, and the dashboard."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.core import charts
from apps.core.errors import ValidationError
from apps.core.tenancy import tenant_context
from apps.evaluations import services
from apps.notifications.services import notify
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from conftest import login

# --- charts (pure) -------------------------------------------------------------------------------


def test_clean_ticks_and_compact_numbers():
    assert charts.nice_ticks(9100) == [0, 2500, 5000, 7500, 10000]
    assert charts.nice_ticks(3) == [0, 1, 2, 3]
    assert charts.nice_ticks(0) == [0, 1]
    assert (charts.compact(1284), charts.compact(12900), charts.compact(4_200_000),
            charts.compact(950)) == ("1.3K", "12.9K", "4.2M", "950")


def test_columns_are_thin_rounded_and_labelled_sparingly():
    chart = charts.columns([charts.Point(str(i), v) for i, v in enumerate([3, 9, 0, 4])])
    marks = chart["marks"]
    assert [m["show_value"] for m in marks] == [False, True, False, True]  # highest and last
    assert marks[2]["path"] == ""  # nothing to draw for zero
    assert "Q" in marks[0]["path"]  # the rounded top
    width = charts.columns([charts.Point("a", 1)])["marks"][0]
    assert width["hit_w"] > charts.MAX_THICKNESS  # the hit target is the whole band
    bars = charts.bars([charts.Point("Sales", 10), charts.Point("Admin", 30)])
    assert [m["label"] for m in bars["marks"]] == ["Admin", "Sales"]  # longest first


# --- evaluations ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_evaluation_and_its_card(tenant_a, make_employee):
    from apps.employees.services import CompensationInput, change_pay

    person = make_employee(tenant_a, 1, name="Mona Adel", salary=D(6000), hired_on=date(2024, 3, 1))
    with tenant_context(tenant_a.id):
        change_pay(person.pk, CompensationInput(effective_from=date(2026, 7, 1), salary=D(7000),
                                                insured_salary=D(5500)))
        with pytest.raises(ValidationError) as empty:
            services.save(services.EvaluationInput(person.pk, 2026, date(2026, 12, 20)))
        assert "note_1" in empty.value.fields
        row = services.save(services.EvaluationInput(person.pk, 2026, date(2026, 12, 20),
                                                     note_1="Reliable", note_3="Leads the team"))
        assert row.number == 1 and row.notes == ["Reliable", "Leads the team"]
        facts = services.card(row)
        assert facts["pay"]["starting_salary"] == D(6000)
        assert facts["pay"]["yearly_base"] == D(84000)  # the pay at the year's end × 12
        assert facts["pay"]["insured_salary"] == D(5500)
        assert facts["pay"]["total"] == D(84000)  # no approved payslips with items yet


@pytest.mark.django_db
def test_evaluation_pages_and_who_sees_pay(tenant_a, make_employee, make_member):
    person = make_employee(tenant_a, 1, name="Mona Adel")
    owner = login(tenant_a, language="en")
    made = owner.post("/api/web/evaluations/evaluations/", {
        "employee_id": person.pk, "year": 2026, "evaluated_on": "2026-12-20",
        "note_1": "Reliable"}, content_type="application/json")
    assert made.status_code == 201
    pk = made.json()["id"]
    for path in ("/people/evaluations/", "/people/evaluations/new/",
                 f"/people/evaluations/{pk}/"):
        assert owner.get(path).status_code == 200, path
    make_member(tenant_a, "viewer", "viewer")
    viewer = login(tenant_a, "viewer", language="en")
    page = viewer.get(f"/people/evaluations/{pk}/").content.decode()
    assert "Reliable" in page and "Yearly base pay" not in page  # no pay permission
    assert viewer.post("/api/web/evaluations/evaluations/", {}, content_type="application/json"
                       ).status_code == 403


# --- the bell and the dashboard ------------------------------------------------------------------


@pytest.mark.django_db
def test_the_bell_counts_lists_and_marks_read(tenant_a, make_employee):
    from apps.attendance import leave
    from apps.attendance.models import LeaveType
    from apps.iam.models import Membership

    person = make_employee(tenant_a, 1)
    with tenant_context(tenant_a.id):
        owner = Membership.objects.get(username="owner")
        notify([owner], "movement", "An incentive was given to you")
        leave.request_leave(leave.LeaveRequestInput(
            person.pk, LeaveType.objects.filter(uses_annual_balance=True).first().pk,
            date(2027, 3, 2), date(2027, 3, 3)))
    client = login(tenant_a, language="en")
    assert client.get("/api/web/notifications/?count=1").json() == {"unread": 1}
    bell = client.get("/api/web/notifications/").json()
    assert bell["results"][0]["title"] == "An incentive was given to you"
    assert {a["label"] for a in bell["attention"]} >= {"Leave to decide"}
    read = client.post(f"/api/web/notifications/{bell['results'][0]['id']}/read/")
    assert read.json() == {"unread": 0}
    page = client.get("/notifications/").content.decode()
    assert "Leave to decide" in page and "An incentive was given to you" in page
    assert 'data-bell' in client.get("/").content.decode()


@pytest.mark.django_db
def test_the_dashboard_shows_what_each_member_may_see(tenant_a, make_employee, make_member):
    from apps.payroll import services as payroll

    TenantFeature.objects.create(tenant=tenant_a, key="attendance", enabled=False)
    features.forget(tenant_a.pk)
    make_employee(tenant_a, 1, salary=D(6000))
    with tenant_context(tenant_a.id):
        run = payroll.create_run(payroll.RunInput(frequency="monthly", day=date(2026, 9, 15)))
        payroll.approve_run(run.pk)
    owner = login(tenant_a, language="en").get("/").content.decode()
    assert "Net pay by department" in owner and "New hires each month" in owner
    assert "Present each day" not in owner  # attendance is off
    assert "6K" in owner  # the last approved net, compact
    make_member(tenant_a, "viewer", "viewer")
    viewer = login(tenant_a, "viewer", language="en").get("/").content.decode()
    assert "Employees working" in viewer and "Net pay by department" not in viewer
