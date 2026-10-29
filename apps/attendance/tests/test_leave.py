"""Leave requests, the yearly balance, hourly leave and the approval state machine."""

from datetime import date
from decimal import Decimal

import pytest

from apps.attendance.models import HourlyLeave, LeaveRequest, LeaveType, RequestStatus
from apps.core.tenancy import tenant_context
from apps.policies.models import PublicHoliday
from conftest import login

pytestmark = pytest.mark.django_db

LEAVE = "/api/web/attendance/leave-requests/"
HOURLY = "/api/web/attendance/hourly-leave/"


def _annual(tenant):
    with tenant_context(tenant.id):
        return LeaveType.objects.get(uses_annual_balance=True).pk


def _ask(client, employee, start, end, approve=False, leave_type=None, tenant=None):
    return client.post(LEAVE, {"employee_id": employee.pk,
                               "leave_type_id": leave_type or _annual(tenant),
                               "start_date": start, "end_date": end, "approve": approve},
                       content_type="application/json")


def test_new_clients_get_leave_types(tenant_a):
    with tenant_context(tenant_a.id):
        assert LeaveType.objects.count() == 3
        assert LeaveType.objects.filter(uses_annual_balance=True).count() == 1
        assert LeaveType.objects.filter(paid=False).count() == 1


def test_leave_days_skip_days_off_and_holidays(tenant_a, make_employee):
    employee = make_employee(tenant_a)  # Fridays off
    with tenant_context(tenant_a.id):
        PublicHoliday.objects.create(date=date(2026, 10, 6), name="Armed Forces Day")
    response = _ask(login(tenant_a), employee, "2026-10-04", "2026-10-10", tenant=tenant_a)
    assert response.status_code == 201, response.content
    assert response.json()["days"] == 5  # 7 days less a Friday and a holiday
    assert response.json()["status"] == "pending"


def test_the_balance_is_checked_when_approving(tenant_a, make_employee):
    employee = make_employee(tenant_a, annual_leave_days=5, days_off=())
    client = login(tenant_a)
    first = _ask(client, employee, "2026-03-01", "2026-03-04", approve=True, tenant=tenant_a)
    assert first.json()["status"] == "approved"
    second = _ask(client, employee, "2026-04-01", "2026-04-02", tenant=tenant_a).json()
    refused = client.post(f"{LEAVE}{second['id']}/approve/", content_type="application/json")
    assert refused.json()["error"]["code"] == "ATTENDANCE_LEAVE_BALANCE"
    # Unpaid leave doesn't use the balance.
    with tenant_context(tenant_a.id):
        unpaid = LeaveType.objects.get(paid=False).pk
    ok = _ask(client, employee, "2026-05-01", "2026-05-02", approve=True, leave_type=unpaid)
    assert ok.json()["status"] == "approved"


def test_requests_may_not_overlap_or_cross_years(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    assert _ask(client, employee, "2026-03-01", "2026-03-05", tenant=tenant_a).status_code == 201
    clash = _ask(client, employee, "2026-03-05", "2026-03-08", tenant=tenant_a)
    assert "start_date" in clash.json()["error"]["fields"]
    across = _ask(client, employee, "2026-12-30", "2027-01-02", tenant=tenant_a)
    assert "end_date" in across.json()["error"]["fields"]
    only_off = _ask(client, employee, "2026-03-13", "2026-03-13", tenant=tenant_a)  # a Friday
    assert "end_date" in only_off.json()["error"]["fields"]


def test_the_state_machine(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    request = _ask(client, employee, "2026-03-01", "2026-03-02", tenant=tenant_a).json()
    rejected = client.post(f"{LEAVE}{request['id']}/reject/", {"note": "Busy week"},
                           content_type="application/json").json()
    assert rejected["status"] == "rejected" and rejected["decision_note"] == "Busy week"
    again = client.post(f"{LEAVE}{request['id']}/approve/", content_type="application/json")
    assert again.status_code == 409 and again.json()["error"]["code"] == "ATTENDANCE_REQUEST_STATE"
    # A rejected request no longer blocks the days.
    approved = _ask(client, employee, "2026-03-01", "2026-03-02", approve=True,
                    tenant=tenant_a).json()
    cancelled = client.post(f"{LEAVE}{approved['id']}/cancel/", content_type="application/json")
    assert cancelled.json()["status"] == "cancelled"
    with tenant_context(tenant_a.id):
        assert LeaveRequest.objects.filter(status=RequestStatus.CANCELLED).count() == 1


def test_approving_needs_the_permission_and_the_branch(tenant_a, make_employee, make_member):
    employee = make_employee(tenant_a)
    make_member(tenant_a, "val", "viewer")
    viewer = login(tenant_a, "val")
    assert viewer.get(LEAVE).status_code == 200
    assert _ask(viewer, employee, "2026-03-01", "2026-03-02", tenant=tenant_a).status_code == 403
    request = _ask(login(tenant_a), employee, "2026-03-01", "2026-03-02", tenant=tenant_a).json()
    assert viewer.post(f"{LEAVE}{request['id']}/approve/",
                       content_type="application/json").status_code == 403


def test_hourly_leave_within_the_monthly_allowance(tenant_a, make_employee):
    employee = make_employee(tenant_a, permission_hours=Decimal(2))
    client = login(tenant_a)

    def ask(day, start, end, approve=True):
        return client.post(HOURLY, {"employee_id": employee.pk, "work_date": day,
                                    "starts_at": start, "ends_at": end, "approve": approve},
                           content_type="application/json")

    first = ask("2026-10-05", "10:00", "11:30")
    assert first.status_code == 201 and first.json()["minutes"] == 90
    over = ask("2026-10-06", "10:00", "11:00")
    assert over.json()["error"]["code"] == "ATTENDANCE_HOURLY_ALLOWANCE"
    with tenant_context(tenant_a.id):
        assert not HourlyLeave.objects.filter(work_date=date(2026, 10, 6)).exists()  # rolled back
    assert ask("2026-11-02", "10:00", "11:00").status_code == 201  # a new month
    same_day = ask("2026-10-05", "15:00", "15:30", approve=False)
    assert "work_date" in same_day.json()["error"]["fields"]


def test_approved_leave_and_hours_show_on_the_days(tenant_a, make_employee):
    from apps.attendance.domain.days import Status
    from apps.attendance.selectors import evaluate

    employee = make_employee(tenant_a, permission_hours=Decimal(4))
    client = login(tenant_a)
    _ask(client, employee, "2026-10-05", "2026-10-05", approve=True, tenant=tenant_a)
    client.post(HOURLY, {"employee_id": employee.pk, "work_date": "2026-10-06",
                         "starts_at": "09:00", "ends_at": "10:00", "approve": True},
                content_type="application/json")
    with tenant_context(tenant_a.id):
        monday, tuesday = evaluate([employee], date(2026, 10, 5), date(2026, 10, 6),
                                   today=date(2026, 10, 28))[employee.pk]
    assert monday.status == Status.LEAVE and monday.paid
    assert tuesday.status == Status.ABSENT and tuesday.hourly_minutes == 60
