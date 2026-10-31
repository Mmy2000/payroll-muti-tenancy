"""Where an employee worked and as what, by date. A transfer never rewrites the past, a closed
month's figures stay where they were, and someone can be hired again."""

from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.attendance.domain.days import Status
from apps.attendance.selectors import evaluate
from apps.core.errors import DomainError, PermissionDenied, ValidationError
from apps.core.tenancy import tenant_context
from apps.employees.domain.employment import closed_periods
from apps.employees.models import Employee, EmployeeAssignment
from apps.employees.services import employees
from apps.iam.authz import build_actor
from apps.iam.models import Membership
from apps.org import services as org
from apps.org.models import Branch, Position
from apps.policies.models import PublicHoliday
from conftest import login

pytestmark = pytest.mark.django_db
START = date(2025, 1, 1)


@pytest.fixture
def two(tenant_a):
    with tenant_context(tenant_a.id):
        return Branch.objects.get(code=1), org.create_branch(org.BranchInput(code=2, name="B"))


def _day(person, day):
    return evaluate(Employee.objects.filter(pk=person.pk), day, day)[person.pk][0]


def _move(person, branch, day, **values):
    return employees.AssignmentInput(effective_from=day, branch_id=branch.pk, **values)


def test_a_new_employee_starts_with_one_assignment(tenant_a, make_employee):
    person = make_employee(tenant_a, 7, job_title="Accountant")
    with tenant_context(tenant_a.id):
        row = EmployeeAssignment.objects.get(employee=person)
        assert (row.effective_from, row.branch_id) == (START, person.branch_id)
        assert row.job_title == "Accountant"


def test_a_transfer_leaves_past_holidays_where_they_were(tenant_a, two, make_employee):
    a, b = two
    holiday = date(2026, 3, 3)
    person = make_employee(tenant_a, 7, branch=a)
    with tenant_context(tenant_a.id):
        PublicHoliday.objects.create(date=holiday, name="Branch A day", branch=a)
        assert _day(person, holiday).status == Status.HOLIDAY
        employees.change_assignment(person.pk, _move(person, b, date(2026, 6, 1)))
        fresh = Employee.objects.get(pk=person.pk)
        assert fresh.branch_id == b.pk
        assert _day(fresh, holiday).status == Status.HOLIDAY
        assert _day(fresh, holiday).paid


def test_a_change_on_the_card_starts_today_and_keeps_the_past(tenant_a, two, make_employee):
    a, b = two
    holiday = date(2026, 3, 3)
    person = make_employee(tenant_a, 7, branch=a)
    with tenant_context(tenant_a.id):
        PublicHoliday.objects.create(date=holiday, name="Branch A day", branch=a)
        employees.update_employee(person.pk, employees.EmployeeInput(
            code=7, name=person.name, branch_id=b.pk, hired_on=START))
        rows = EmployeeAssignment.objects.filter(employee=person).order_by("effective_from")
        assert [row.branch_id for row in rows] == [a.pk, b.pk]
        assert rows.last().effective_from == timezone.localdate()
        assert _day(Employee.objects.get(pk=person.pk), holiday).status == Status.HOLIDAY


def test_a_dated_transfer_ahead_waits_for_its_day(tenant_a, two, make_employee):
    a, b = two
    person = make_employee(tenant_a, 7, branch=a)
    soon = timezone.localdate() + timedelta(days=3)
    with tenant_context(tenant_a.id):
        employees.change_assignment(person.pk, _move(person, b, soon))
        assert Employee.objects.get(pk=person.pk).branch_id == a.pk
        EmployeeAssignment.objects.filter(employee=person, branch=b).update(
            effective_from=timezone.localdate())
        assert employees.apply_due_assignments() == 1
        assert Employee.objects.get(pk=person.pk).branch_id == b.pk


def test_a_transfer_needs_both_branches(tenant_a, two, make_employee, make_member):
    a, b = two
    person = make_employee(tenant_a, 7, branch=a)
    member = make_member(tenant_a, "local", "manager", branches=[a])
    with tenant_context(tenant_a.id):
        actor = build_actor(Membership.objects.get(pk=member.pk))
        with pytest.raises(PermissionDenied):
            employees.change_assignment(person.pk, _move(person, b, date(2026, 6, 1)), actor=actor)


def test_a_transfer_into_an_approved_period_is_refused(tenant_a, two, make_employee, monkeypatch):
    from apps.core import locks

    a, b = two
    person = make_employee(tenant_a, 7, branch=a)
    monkeypatch.setattr(locks, "period_locked", lambda pk, start, end=None: True)
    with tenant_context(tenant_a.id), pytest.raises(DomainError) as refused:
        employees.change_assignment(person.pk, _move(person, b, date(2026, 6, 1)))
    assert refused.value.code == "PAYROLL_LOCKED"


def test_a_mistaken_transfer_can_be_removed(tenant_a, two, make_employee):
    a, b = two
    person = make_employee(tenant_a, 7, branch=a)
    with tenant_context(tenant_a.id):
        row = employees.change_assignment(person.pk, _move(person, b, date(2026, 6, 1)))
        employees.delete_assignment(row.pk)
        assert Employee.objects.get(pk=person.pk).branch_id == a.pk
        first = EmployeeAssignment.objects.get(employee=person)
        with pytest.raises(DomainError):
            employees.delete_assignment(first.pk)


def test_a_corrected_hiring_date_moves_the_first_row(tenant_a, make_employee):
    person = make_employee(tenant_a, 7)
    earlier = date(2024, 6, 1)
    with tenant_context(tenant_a.id):
        employees.update_employee(person.pk, employees.EmployeeInput(
            code=7, name=person.name, branch_id=person.branch_id, hired_on=earlier))
        assert EmployeeAssignment.objects.get(employee=person).effective_from == earlier


def test_a_position_names_the_job_and_can_be_shared(tenant_a, two, make_employee):
    a, _b = two
    first = make_employee(tenant_a, 1, branch=a)
    second = make_employee(tenant_a, 2, branch=a)
    with tenant_context(tenant_a.id):
        job = org.save_position(org.PositionInput(name="Accountant"))
        for person in (first, second):
            employees.change_assignment(person.pk, _move(person, a, date(2026, 6, 1),
                                                         position_id=job.pk))
        fresh = Employee.objects.get(pk=first.pk)
        assert (fresh.position_id, fresh.job_title) == (job.pk, "Accountant")
        assert Employee.objects.filter(position=job).count() == 2


def test_a_promotion_is_a_dated_row(tenant_a, two, make_employee):
    a, _b = two
    person = make_employee(tenant_a, 7, branch=a, job_title="Clerk")
    with tenant_context(tenant_a.id):
        employees.change_assignment(person.pk, _move(person, a, date(2026, 6, 1),
                                                     job_title="Supervisor"))
        titles = list(EmployeeAssignment.objects.filter(employee=person)
                      .order_by("effective_from").values_list("job_title", flat=True))
        assert titles == ["Clerk", "Supervisor"]


def test_nobody_gets_an_inactive_position(tenant_a, two, make_employee):
    a, _b = two
    person = make_employee(tenant_a, 7, branch=a)
    with tenant_context(tenant_a.id):
        job = org.save_position(org.PositionInput(name="Old job"))
        org.set_position_active(job.pk, False)
        with pytest.raises(ValidationError) as refused:
            employees.change_assignment(person.pk, _move(person, a, date(2026, 6, 1),
                                                         position_id=job.pk))
        assert "position_id" in refused.value.fields


def test_two_positions_cant_share_a_name(tenant_a):
    with tenant_context(tenant_a.id):
        org.save_position(org.PositionInput(name="Accountant"))
        with pytest.raises(ValidationError):
            org.save_position(org.PositionInput(name="Accountant"))


# --- hired again ------------------------------------------------------------------------------


def test_someone_who_left_is_hired_again_on_the_same_record(tenant_a, two, make_employee):
    a, b = two
    person = make_employee(tenant_a, 7, branch=a, national_id="29001011234567")
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, date(2025, 6, 30), "resigned")
        employees.rehire(person.pk, _move(person, b, date(2026, 1, 1), job_title="Back"))
        fresh = Employee.objects.get(pk=person.pk)
        assert fresh.hired_on == date(2026, 1, 1)
        assert fresh.left_on is None and fresh.is_active
        assert fresh.branch_id == b.pk
        closed = EmployeeAssignment.objects.get(employee=person, ended_on__isnull=False)
        assert (closed.effective_from, closed.ended_on) == (START, date(2025, 6, 30))
        assert closed.leave_reason == "resigned"


def test_both_periods_count_and_the_gap_doesnt(tenant_a, make_employee):
    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, date(2025, 6, 30))
        employees.rehire(person.pk, _move(person, person.branch, date(2026, 1, 1)))
        fresh = Employee.objects.get(pk=person.pk)
        assert _day(fresh, date(2025, 3, 3)).status != Status.NOT_EMPLOYED
        assert _day(fresh, date(2025, 9, 1)).status == Status.NOT_EMPLOYED
        assert _day(fresh, date(2026, 3, 3)).status != Status.NOT_EMPLOYED


def test_periods_come_from_the_rows():
    class Row:
        def __init__(self, start, ended=None):
            self.effective_from, self.ended_on = start, ended

    rows = [Row(date(2020, 1, 1)), Row(date(2020, 6, 1), date(2020, 12, 31)), Row(date(2021, 6, 1))]
    assert closed_periods(rows) == [(date(2020, 1, 1), date(2020, 12, 31))]


def test_only_someone_who_left_is_hired_again(tenant_a, make_employee):
    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id), pytest.raises(DomainError):
        employees.rehire(person.pk, _move(person, person.branch, date(2026, 1, 1)))


def test_the_new_date_is_after_the_old_period(tenant_a, make_employee):
    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, date(2025, 6, 30))
        with pytest.raises(ValidationError) as refused:
            employees.rehire(person.pk, _move(person, person.branch, date(2025, 6, 30)))
        assert "effective_from" in refused.value.fields


# --- the page and the API --------------------------------------------------------------------


def test_the_employee_page_shows_and_changes_assignments(tenant_a, two, make_employee):
    a, b = two
    person = make_employee(tenant_a, 7, branch=a)
    client = login(tenant_a, language="en")
    assert "Transfer or change job" in client.get(
        reverse("employee", args=[person.pk])).content.decode()
    saved = client.post(reverse("employee-assignment", args=[person.pk]),
                        {"effective_from": "2026-06-01", "branch_id": b.pk},
                        content_type="application/json")
    assert saved.status_code == 200
    with tenant_context(tenant_a.id):
        row = EmployeeAssignment.objects.get(employee=person, branch=b)
    assert client.delete(reverse("assignment-change-detail", args=[row.pk])).status_code == 204


def test_positions_have_their_pages(tenant_a):
    client = login(tenant_a, language="en")
    made = client.post(reverse("position-list"), {"name": "Accountant"},
                       content_type="application/json")
    assert made.status_code == 201
    assert "Accountant" in client.get(reverse("positions")).content.decode()
    pk = made.json()["id"]
    assert client.get(reverse("position-edit", args=[pk])).status_code == 200
    assert client.post(reverse("position-deactivate", args=[pk])).status_code == 200


# --- what existed before ---------------------------------------------------------------------


def test_past_transfers_are_rebuilt_from_the_audit_trail(tenant_a, two, make_employee):
    a, b = two
    person = make_employee(tenant_a, 7, branch=a, job_title="Clerk")
    with tenant_context(tenant_a.id):
        Employee.objects.filter(pk=person.pk).update(branch=b, job_title="Clerk")
        EmployeeAssignment.objects.filter(employee=person).delete()
        migration = import_module("apps.employees.migrations.0012_backfill_assignments")
        migration.rebuild(django_apps, tenant_a.id, connection.alias)
        rows = list(EmployeeAssignment.objects.filter(employee=person)
                    .order_by("effective_from"))
        assert [row.branch_id for row in rows] == [a.pk, b.pk]
        assert rows[0].effective_from == START
        assert rows[1].effective_from == timezone.localdate()
        job = Position.objects.get(name="Clerk")
        assert Employee.objects.get(pk=person.pk).position_id == job.pk
        assert Decimal(rows[0].position_id) == job.pk
