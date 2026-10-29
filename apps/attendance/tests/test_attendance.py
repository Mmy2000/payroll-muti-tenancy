"""Attendance through the API and the pages: punches, manual entries, the daily sheet."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.attendance.domain.days import Status
from apps.attendance.models import AttendanceDay, Punch, PunchSource
from apps.attendance.selectors import evaluate
from apps.core.tenancy import tenant_context
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from apps.policies.models import PublicHoliday
from conftest import login

pytestmark = pytest.mark.django_db

CAIRO = ZoneInfo("Africa/Cairo")
MONDAY = date(2026, 10, 5)


def _punch(tenant, employee, day, hour, minute=0):
    with tenant_context(tenant.id):
        return Punch.objects.create(employee=employee, source=PunchSource.DEVICE,
                                    at=datetime.combine(day, time(hour, minute), tzinfo=CAIRO))


def _days(tenant, employee, start, end):
    with tenant_context(tenant.id), timezone.override(CAIRO):
        return evaluate([employee], start, end, today=date(2026, 10, 28))[employee.pk]


def test_punches_make_a_present_day(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    _punch(tenant_a, employee, MONDAY, 9, 25)
    _punch(tenant_a, employee, MONDAY, 17, 5)
    monday, tuesday = _days(tenant_a, employee, MONDAY, MONDAY + timedelta(days=1))
    assert monday.status == Status.PRESENT and monday.late_minutes == 25
    assert monday.extra_minutes == 5
    assert tuesday.status == Status.ABSENT


def test_a_night_shift_counts_on_the_day_it_starts(tenant_a, make_employee):
    employee = make_employee(tenant_a, starts_at=time(22), ends_at=time(6))
    _punch(tenant_a, employee, MONDAY, 22, 0)
    _punch(tenant_a, employee, MONDAY + timedelta(days=1), 6, 0)
    monday, tuesday = _days(tenant_a, employee, MONDAY, MONDAY + timedelta(days=1))
    assert monday.status == Status.PRESENT and monday.worked_minutes == 480
    assert tuesday.status == Status.ABSENT


def test_holidays_of_another_branch_do_not_apply(tenant_a, make_employee):
    from apps.org.models import Branch

    employee = make_employee(tenant_a)
    with tenant_context(tenant_a.id):
        other = Branch.objects.create(code=2, name="Alexandria")
        PublicHoliday.objects.create(date=MONDAY, name="Local day", branch=other)
        PublicHoliday.objects.create(date=MONDAY + timedelta(days=1), name="National day")
    monday, tuesday = _days(tenant_a, employee, MONDAY, MONDAY + timedelta(days=1))
    assert monday.status == Status.ABSENT
    assert tuesday.status == Status.HOLIDAY and tuesday.label == "National day"


def test_punches_are_append_only(tenant_a, make_employee):
    punch = _punch(tenant_a, make_employee(tenant_a), MONDAY, 9)
    with tenant_context(tenant_a.id), pytest.raises(DatabaseError), transaction.atomic():
        Punch.objects.filter(pk=punch.pk).update(at=punch.at + timedelta(hours=1))


def test_a_manual_entry_wins_and_clearing_it_brings_the_clock_back(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    _punch(tenant_a, employee, MONDAY, 9, 40)
    _punch(tenant_a, employee, MONDAY, 17)
    client = login(tenant_a)
    saved = client.post("/api/web/attendance/days/", {
        "employee_id": employee.pk, "work_date": "2026-10-05", "kind": "worked",
        "check_in": "09:00", "check_out": "17:00", "note": "Clock was wrong"},
        content_type="application/json")
    assert saved.status_code == 201, saved.content
    (monday,) = _days(tenant_a, employee, MONDAY, MONDAY)
    assert monday.source == "manual" and monday.late_minutes == 0
    with tenant_context(tenant_a.id):
        assert Punch.objects.filter(employee=employee).count() == 2  # untouched
    client.post("/api/web/attendance/days/clear/", {"employee_id": employee.pk,
                                                    "work_date": "2026-10-05"},
                content_type="application/json")
    (monday,) = _days(tenant_a, employee, MONDAY, MONDAY)
    assert monday.source == "clock" and monday.late_minutes == 40


def test_entry_rules(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    ahead = (timezone.localdate() + timedelta(days=3)).isoformat()

    def post(**body):
        return client.post("/api/web/attendance/days/", {"employee_id": employee.pk, **body},
                           content_type="application/json")

    assert "work_date" in post(work_date=ahead, kind="absent").json()["error"]["fields"]
    assert post(work_date=ahead, kind="day_off").status_code == 201  # a day off may be planned
    assert "check_in" in post(work_date="2026-10-05", kind="worked").json()["error"]["fields"]
    early = post(work_date="2024-12-31", kind="absent").json()["error"]["fields"]
    assert "work_date" in early  # before hiring


def test_bulk_present_on_shift_times(tenant_a, make_employee):
    first = make_employee(tenant_a, 1)
    second = make_employee(tenant_a, 2, starts_at=time(8), ends_at=time(14))
    response = login(tenant_a).post("/api/web/attendance/days/bulk/", {
        "employee_ids": [first.pk, second.pk], "work_date": "2026-10-05", "kind": "worked",
        "shift_times": True}, content_type="application/json")
    assert response.json() == {"saved": 2}
    with tenant_context(tenant_a.id), timezone.override(CAIRO):
        entry = AttendanceDay.objects.get(employee=second)
        assert timezone.localtime(entry.check_in).time() == time(8)
        assert timezone.localtime(entry.check_out).time() == time(14)


def test_branch_managers_only_correct_their_branch(tenant_a, make_employee, make_member):
    from apps.org.models import Branch

    with tenant_context(tenant_a.id):
        other = Branch.objects.create(code=2, name="Alexandria")
    head = make_employee(tenant_a, 1)
    there = make_employee(tenant_a, 2, branch=other)
    make_member(tenant_a, "mona", "manager", branches=[other])
    manager = login(tenant_a, "mona")
    body = {"work_date": "2026-10-05", "kind": "absent"}
    assert manager.post("/api/web/attendance/days/", {**body, "employee_id": head.pk},
                        content_type="application/json").status_code == 404
    assert manager.post("/api/web/attendance/days/", {**body, "employee_id": there.pk},
                        content_type="application/json").status_code == 201
    page = manager.get("/attendance/?date=2026-10-05").content.decode()
    assert "Employee 2" in page and "Employee 1" not in page


def test_pages_render_in_the_clients_time_zone(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    _punch(tenant_a, employee, MONDAY, 9, 5)  # 06:05 UTC
    client = login(tenant_a, language="en")
    page = client.get("/attendance/?date=2026-10-05").content.decode()
    assert "09:05" in page and "06:05" not in page
    month = client.get(f"/attendance/employees/{employee.pk}/?month=2026-10").content.decode()
    assert "09:05" in month
    for path in ("/attendance/import/", "/attendance/leave/", "/attendance/leave/new/",
                 "/attendance/leave/types/", "/attendance/hourly/", "/attendance/hourly/new/"):
        assert client.get(path).status_code == 200, path


def test_switching_attendance_off_takes_lateness_and_overtime_with_it(tenant_a):
    TenantFeature.objects.create(tenant=tenant_a, key="attendance", enabled=False)
    features.forget(tenant_a.pk)
    for key in ("lateness", "overtime", "leave", "hourly_leave", "attendance_import"):
        assert not features.is_enabled(tenant_a.pk, key), key
    owner = login(tenant_a)
    assert owner.get("/attendance/").status_code == 403
    assert owner.get("/pay-setup/lateness/").status_code == 403
    assert owner.get("/pay-setup/tax/").status_code == 200
