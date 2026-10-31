"""New working hours for a group: from a date, for good or until a last day, never rewriting
earlier days, previewed first."""

from datetime import date, time

import pytest

from apps.core.bulk import BulkFailed
from apps.core.history import in_effect
from apps.core.tenancy import tenant_context
from apps.org.models import Branch
from conftest import login

from ..selectors import Group
from ..services import employees
from ..services.group_hours import GroupHoursInput, change_hours_for_group

pytestmark = pytest.mark.django_db
START = date(2026, 11, 1)


def _hours(employee, day):
    row = in_effect(employee.schedules.all(), day)
    return row.starts_at, row.ends_at, list(row.days_off)


def _ramadan(group, **extra):
    return GroupHoursInput(group=group, effective_from=START, starts_at=time(10),
                           ends_at=time(15), **extra)


def test_hours_for_a_range_then_back_to_the_usual(tenant_a, make_employee):
    first = make_employee(tenant_a, 1)
    second = make_employee(tenant_a, 2, starts_at=time(8), ends_at=time(16), days_off=(5, 6))
    with tenant_context(tenant_a.id):
        group = Group("branch", id=Branch.objects.get(code=1).pk)
        data = _ramadan(group, until=date(2026, 11, 30))
        preview = change_hours_for_group(data)
        assert preview.passed == 2 and first.schedules.count() == 1  # nothing saved yet
        change_hours_for_group(data, save=True)

        assert _hours(first, date(2026, 10, 31)) == (time(9), time(17), [4])  # untouched
        assert _hours(first, START) == (time(10), time(15), [4])  # own days off kept
        assert _hours(second, date(2026, 11, 30)) == (time(10), time(15), [5, 6])
        assert _hours(second, date(2026, 12, 1)) == (time(8), time(16), [5, 6])  # back


def test_a_change_inside_the_range_fails_that_row(tenant_a, make_employee):
    first = make_employee(tenant_a, 1)
    second = make_employee(tenant_a, 2)
    with tenant_context(tenant_a.id):
        employees.change_schedule(second.pk, employees.ScheduleInput(
            effective_from=date(2026, 11, 15), starts_at=time(7), ends_at=time(15)))
        data = _ramadan(Group("employees", (first.pk, second.pk)), until=date(2026, 11, 30),
                        days_off=(4, 5))
        with pytest.raises(BulkFailed) as failed:
            change_hours_for_group(data, save=True)
        assert "inside this range" in failed.value.outcome.rows[1].errors[0]
        assert first.schedules.count() == 1  # nothing kept

        kept = change_hours_for_group(data, save=True, skip_failed=True)
        assert kept.saved == 1
        assert _hours(first, START) == (time(10), time(15), [4, 5])
        assert _hours(second, START) == (time(9), time(17), [4])


def test_a_later_change_is_kept_and_said(tenant_a, make_employee):
    first = make_employee(tenant_a, 1)
    with tenant_context(tenant_a.id):
        employees.change_schedule(first.pk, employees.ScheduleInput(
            effective_from=date(2027, 1, 1), starts_at=time(8), ends_at=time(16)))
        outcome = change_hours_for_group(_ramadan(Group("employees", (first.pk,))), save=True)
        assert "2027-01-01" in outcome.rows[0].warnings[0]
        assert _hours(first, date(2027, 1, 1))[0] == time(8)


def test_the_api_previews_then_saves(tenant_a, make_employee):
    first = make_employee(tenant_a, 1)
    client = login(tenant_a)
    body = {"group_kind": "employees", "employee_ids": [first.pk],
            "effective_from": "2026-11-01", "starts_at": "10:00", "ends_at": "15:00"}
    url = "/api/web/employees/group-hours/"
    assert client.post(url, body, content_type="application/json").status_code == 200
    saved = client.post(url, {**body, "save": True}, content_type="application/json")
    assert saved.status_code == 201 and saved.json()["saved"] == 1
