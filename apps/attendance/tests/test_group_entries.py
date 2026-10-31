"""Hourly leave and attendance for a group (apps/core/bulk.py): a preview that saves nothing,
each employee checked by the same rules as one at a time, nothing saved twice."""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone, translation

from apps.attendance.models import AttendanceDay, HourlyLeave, Punch, PunchSource, RequestStatus
from apps.attendance.selectors import evaluate
from apps.core.bulk import BulkFailed
from apps.core.errors import ValidationError
from apps.core.tenancy import tenant_context
from apps.employees.selectors import Group
from apps.org.models import Branch
from conftest import login

from ..services import entries, hourly

pytestmark = pytest.mark.django_db
CAIRO = ZoneInfo("Africa/Cairo")
MONDAY = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):  # the messages are checked by their words
        yield


@pytest.fixture
def people(tenant_a, make_employee):
    return [make_employee(tenant_a, code, permission_hours=Decimal(2)) for code in (1, 2)]


def _group(*employees) -> Group:
    return Group("employees", tuple(e.pk for e in employees))


def _leave(group, *spans, **extra):
    return hourly.GroupHourlyLeaveInput(group=group, work_date=MONDAY,
                                        spans=tuple((time(*a), time(*b)) for a, b in spans),
                                        **extra)


# --- hourly leave ----------------------------------------------------------------------------


def test_several_hourly_leaves_a_day_but_never_overlapping(tenant_a, people):
    first = people[0]
    with tenant_context(tenant_a.id):
        for start, end in ((10, 11), (11, 12), (23, 1)):  # touching, and past midnight
            hourly.record_hourly_leave(hourly.HourlyLeaveInput(
                first.pk, MONDAY, time(start), time(end)))
        for start, end in ((10, 30), (11, 30)), ((23, 30), (0, 30)):
            with pytest.raises(ValidationError) as refused:
                hourly.record_hourly_leave(hourly.HourlyLeaveInput(
                    first.pk, MONDAY, time(*start), time(*end)))
            assert "starts_at" in refused.value.fields
        assert HourlyLeave.objects.filter(employee=first).count() == 3


def test_a_group_preview_saves_nothing_and_saving_twice_saves_once(tenant_a, people):
    with tenant_context(tenant_a.id):
        data = _leave(_group(*people), ((10, 0), (11, 0)), ((14, 0), (14, 30)))
        preview = hourly.record_hourly_leave_for_group(data)
        assert (preview.passed, preview.failed, preview.saved) == (4, 0, 0)
        assert [row.detail for row in preview.rows[:2]] == ["10:00–11:00", "14:00–14:30"]
        assert not HourlyLeave.objects.exists()

        saved = hourly.record_hourly_leave_for_group(data, save=True)
        assert saved.saved == 4 and HourlyLeave.objects.count() == 4

        with pytest.raises(BulkFailed) as again:  # a second click on "Save"
            hourly.record_hourly_leave_for_group(data, save=True)
        assert again.value.outcome.failed == 4
        assert "overlaps" in again.value.outcome.rows[0].errors[0]
        assert HourlyLeave.objects.count() == 4


def test_overlapping_spans_in_one_request_are_refused(tenant_a, people):
    with tenant_context(tenant_a.id), pytest.raises(ValidationError) as refused:
        hourly.record_hourly_leave_for_group(
            _leave(_group(*people), ((10, 0), (12, 0)), ((11, 0), (13, 0))))
    assert "spans.1" in refused.value.fields


def test_each_employee_has_their_own_allowance(tenant_a, people, make_employee):
    stingy = make_employee(tenant_a, 3, permission_hours=Decimal("0.5"))
    with tenant_context(tenant_a.id):
        data = _leave(_group(people[0], stingy), ((10, 0), (11, 0)))
        preview = hourly.record_hourly_leave_for_group(data)  # not approving: a warning
        assert preview.failed == 0 and "allowance" in preview.rows[1].warnings[0]

        with pytest.raises(BulkFailed):
            hourly.record_hourly_leave_for_group(data, approve=True, save=True)
        kept = hourly.record_hourly_leave_for_group(data, approve=True, save=True,
                                                    skip_failed=True)
        assert (kept.saved, kept.failed) == (1, 1)
        assert "allowance" in kept.rows[1].errors[0]
        assert list(HourlyLeave.objects.values_list("employee_id", "status")) == [
            (people[0].pk, RequestStatus.APPROVED)]


def test_a_department_or_branch_means_those_employed_that_day(tenant_a, people,
                                                              make_employee):
    make_employee(tenant_a, 3, hired_on=date(2026, 11, 1))  # not yet hired on the day
    with tenant_context(tenant_a.id):
        branch = Branch.objects.get(code=1)
        outcome = hourly.record_hourly_leave_for_group(
            _leave(Group("branch", id=branch.pk), ((10, 0), (11, 0))))
        assert [row.employee_id for row in outcome.rows] == [p.pk for p in people]


# --- attendance with times -------------------------------------------------------------------


def _times(group, **extra):
    values = {"work_date": MONDAY, "check_in": time(9), "check_out": time(17),
              "reason": "The device was down", **extra}
    return entries.GroupTimesInput(group=group, **values)


def test_times_for_a_group_each_with_their_own(tenant_a, people):
    first, second = people
    with tenant_context(tenant_a.id), timezone.override(CAIRO):
        data = _times(_group(*people), own_times={second.pk: (time(9, 40), time(18))})
        preview = entries.set_times_for_group(data)
        assert [row.detail for row in preview.rows] == ["09:00 – 17:00", "09:40 – 18:00"]
        assert not AttendanceDay.objects.exists()
        entries.set_times_for_group(data, save=True)
        day = AttendanceDay.objects.get(employee=second)
        assert day.note == "The device was down"
        # judged like clock times: 40 minutes late on a 9:00 shift
        late = evaluate([second], MONDAY, MONDAY, today=date(2026, 10, 28))[second.pk][0]
        assert late.late_minutes == 40 and late.source == "manual"


def test_times_need_a_reason_both_times_and_no_earlier_entry(tenant_a, people):
    first, second = people
    with tenant_context(tenant_a.id), timezone.override(CAIRO):
        with pytest.raises(ValidationError) as refused:
            entries.set_times_for_group(_times(_group(first), reason=" "))
        assert "reason" in refused.value.fields
        missing = entries.set_times_for_group(_times(_group(first), check_out=None))
        assert missing.rows[0].errors == ["Enter the time they left."]

        entries.set_times_for_group(_times(_group(first)), save=True)
        again = entries.set_times_for_group(_times(_group(first, second)))
        assert again.rows[0].errors == ["Already entered by hand for that day."]
        assert again.rows[1].ok
        replaced = entries.set_times_for_group(
            _times(_group(first), check_in=time(8), replace=True), save=True)
        assert replaced.saved == 1
        assert timezone.localtime(AttendanceDay.objects.get(employee=first).check_in).hour == 8


def test_the_preview_warns_about_clock_times_and_days_off(tenant_a, people):
    first, second = people
    friday = date(2026, 10, 9)  # their weekly day off
    with tenant_context(tenant_a.id), timezone.override(CAIRO):
        Punch.objects.create(employee=first, source=PunchSource.DEVICE,
                             at=datetime.combine(MONDAY, time(9, 5), tzinfo=CAIRO))
        warned = entries.set_times_for_group(_times(_group(first)))
        assert "09:05" in warned.rows[0].warnings[0]
        rest = entries.set_times_for_group(_times(_group(second), work_date=friday))
        assert "rest day" in rest.rows[0].warnings[0]


def test_the_group_pages_through_the_api(tenant_a, people, make_member):
    with tenant_context(tenant_a.id):
        alexandria = Branch.objects.create(code=2, name="Alexandria")
    make_member(tenant_a, "alex", "manager", branches=[alexandria])
    client = login(tenant_a, language="en")
    body = {"group_kind": "employees", "employee_ids": [p.pk for p in people],
            "work_date": "2026-10-05", "spans": [{"starts_at": "10:00", "ends_at": "11:00"}]}
    url = "/api/web/attendance/hourly-leave/group/"
    preview = client.post(url, body, content_type="application/json")
    assert preview.status_code == 200 and preview.json()["passed"] == 2
    saved = client.post(url, {**body, "save": True}, content_type="application/json")
    assert saved.status_code == 201 and saved.json()["saved"] == 2
    again = client.post(url, {**body, "save": True}, content_type="application/json")
    assert again.status_code == 422
    assert again.json()["error"]["details"]["failed"] == 2

    times = client.post("/api/web/attendance/days/times/", {
        "group_kind": "employees", "employee_ids": [people[0].pk], "work_date": "2026-10-05",
        "check_in": "09:00", "check_out": "17:00", "reason": "Device down",
        "own_times": [{"employee_id": people[0].pk, "check_in": "10:00",
                       "check_out": "17:00"}]}, content_type="application/json")
    assert times.status_code == 200 and times.json()["rows"][0]["detail"] == "10:00 – 17:00"

    other = login(tenant_a, "alex")  # manages Alexandria only: not these employees
    refused = other.post(url, body, content_type="application/json")
    assert refused.status_code == 400 and "employee_ids" in refused.json()["error"]["fields"]


def test_the_group_pages_show(tenant_a, people, make_member):
    client = login(tenant_a, language="en")
    for path, words in (("/attendance/hourly/group/", "Hourly leave for a group"),
                        ("/attendance/by-hand/", "Attendance by hand for a group"),
                        ("/employees/hours/", "Working hours for a group")):
        page = client.get(path)
        assert page.status_code == 200, path
        html = page.content.decode()
        assert words in html and 'data-bulk-form' in html and "Employee 2" in html
    assert 'href="/attendance/hourly/group/"' in client.get("/attendance/hourly/").content.decode()
    make_member(tenant_a, "viewer")
    viewer = login(tenant_a, "viewer")
    assert viewer.get("/attendance/by-hand/").status_code == 403
