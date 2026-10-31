"""Fingerprint devices: the ADMS protocol, a device's calls end to end, PIN links, commands, and
what each client's devices may reach."""

from datetime import date, datetime

import pytest
from django.test import Client
from django.utils import timezone

from apps.attendance.models import Punch, PunchSource
from apps.core import locks
from apps.core.errors import DomainError, ValidationError
from apps.core.tenancy import tenant_context
from apps.devices.models import CommandStatus, DevicePunch, DeviceUser
from apps.org.models import Branch
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature

from .. import protocol, selectors
from ..services import devices, links

SERIAL = "CEXF201960123"


# --- the protocol (pure) -----------------------------------------------------------------------


def test_punch_lines_are_read_and_bad_ones_skipped():
    body = ("7\t2026-10-05 08:58:12\t0\t1\t0\t0\n"
            "8\t2026-10-05 09:03:00\n"  # no status: 0
            "\t2026-10-05 09:00:00\t0\n"  # no PIN
            "9\tyesterday\t0\n")
    records = protocol.parse_attlog(body)
    assert [(r.pin, r.at, r.status, r.verify) for r in records] == [
        ("7", datetime(2026, 10, 5, 8, 58, 12), 0, 1),
        ("8", datetime(2026, 10, 5, 9, 3), 0, 0)]


def test_users_with_or_without_the_prefix():
    body = "USER PIN=7\tName=Mona Adel\tPri=0\nPIN=8\tName=كريم\nOPLOG 4\t0\t2026-10-05\n"
    assert protocol.parse_users(body) == {"7": "Mona Adel", "8": "كريم"}


def test_a_reply_without_return_is_a_failure():
    replies = protocol.parse_replies("ID=12&Return=0&CMD=INFO\nID=13&Return=-1002\nID=14&CMD=x\n")
    assert [(r.id, r.ok) for r in replies] == [(12, True), (13, False), (14, False)]


def test_the_handshake_is_payroles():
    text = protocol.options("ABC", resend_all=True, utc_offset_hours=3)
    assert text.startswith("GET OPTION FROM: ABC\nATTLOGStamp=0\n")
    assert "TimeZone=3\n" in text and "Delay=10\n" in text and text.endswith("Encrypt=None\n")
    assert protocol.command_lines([]) == "OK\n"
    assert protocol.command_lines([(5, "INFO")]) == "C:5:INFO\n"


# --- a device's calls ---------------------------------------------------------------------------


def _switch_on(tenant):
    TenantFeature.objects.update_or_create(tenant=tenant, key="zk_devices",
                                           defaults={"enabled": True})
    features.forget(tenant.pk)


@pytest.fixture
def device(tenant_a):
    _switch_on(tenant_a)
    with tenant_context(tenant_a.id):
        branch = Branch.objects.get(code=1)
        return devices.save_device(devices.DeviceInput(SERIAL, "Gate", branch.pk))


def _call(tenant, path, *, body=None, **query):
    client = Client(HTTP_HOST=f"{tenant.slug}.localhost")
    query = "&".join(f"{k}={v}" for k, v in {"SN": SERIAL, **query}.items())
    url = f"/iclock/{path}?{query}"
    if body is None:
        return client.get(url)
    return client.post(url, body, content_type="text/plain")


@pytest.mark.django_db
def test_a_device_sends_punches_that_become_attendance(device, tenant_a, make_employee):
    employee = make_employee(tenant_a, 7, name="Mona Adel")
    with tenant_context(tenant_a.id):
        assert links.link_by_code(device.branch_id) == 0  # nobody enrolled yet
    hello = _call(tenant_a, "cdata", options="all", pushver="2.4.1")
    assert hello.status_code == 200 and hello["Content-Type"].startswith("text/plain")
    assert hello.content.decode().startswith(f"GET OPTION FROM: {SERIAL}\n")

    body = ("7\t2026-10-05 08:58:12\t0\t1\n7\t2026-10-05 17:02:00\t1\t1\n"
            "99\t2026-10-05 09:00:00\t0\t1\n")
    assert _call(tenant_a, "cdata", body=body, table="ATTLOG").content == b"OK: 3\n"
    assert _call(tenant_a, "cdata", body=body, table="ATTLOG").content == b"OK: 3\n"  # again
    with tenant_context(tenant_a.id):
        assert DevicePunch.objects.count() == 3  # the same moment twice is one punch
        assert not Punch.objects.exists()  # PIN 7 isn't linked yet
        assert links.link_by_code(device.branch_id) == 1  # PIN 7 = employee code 7
        punches = list(Punch.objects.filter(employee=employee).order_by("at"))
        assert [p.source for p in punches] == [PunchSource.DEVICE] * 2
        assert timezone.localtime(punches[0].at).strftime("%H:%M") == "08:58"
        stranger = DeviceUser.objects.get(pin="99")
        assert stranger.employee is None and stranger.punches.count() == 1
        device.refresh_from_db()
        assert device.last_seen_at is not None and selectors.is_online(device)


@pytest.mark.django_db
def test_users_from_the_device_and_links(device, tenant_a, make_employee):
    first = make_employee(tenant_a, 1)
    second = make_employee(tenant_a, 2)
    _call(tenant_a, "cdata", body="USER PIN=1\tName=First\nUSER PIN=5\tName=Five\n",
          table="OPERLOG")
    with tenant_context(tenant_a.id):
        five = DeviceUser.objects.get(pin="5")
        assert five.name == "Five"
        links.link(five.pk, second.pk)
        with pytest.raises(ValidationError):  # one PIN per employee on a branch's devices
            links.link(DeviceUser.objects.get(pin="1").pk, second.pk)
    _call(tenant_a, "cdata", body="5\t2026-10-05 09:00:00\t0\t1\n", table="ATTLOG")
    with tenant_context(tenant_a.id):
        assert Punch.objects.filter(employee=second).count() == 1
        with pytest.raises(DomainError):  # its punches are someone's attendance now
            links.link(five.pk, first.pk)


@pytest.mark.django_db
def test_commands_one_at_a_time_and_their_replies(device, tenant_a):
    with tenant_context(tenant_a.id):
        test = devices.ask(device.pk, devices.CommandInput(devices.TEST))
        pull = devices.ask(device.pk, devices.CommandInput(
            devices.PULL_PUNCHES, start=date(2026, 10, 1), end=date(2026, 10, 5)))
    first = _call(tenant_a, "getrequest", INFO="Ver 8.0.4,12,10,2311").content.decode()
    assert first == f"C:{test.pk}:INFO\n"
    second = _call(tenant_a, "getrequest").content.decode()
    assert second.startswith(f"C:{pull.pk}:DATA QUERY ATTLOG StartTime=2026-10-01 00:00:00")
    assert _call(tenant_a, "getrequest").content == b"OK\n"
    _call(tenant_a, "devicecmd", body=f"ID={test.pk}&Return=0&CMD=INFO\nID={pull.pk}&CMD=DATA\n")
    with tenant_context(tenant_a.id):
        test.refresh_from_db()
        pull.refresh_from_db()
        assert (test.status, pull.status) == (CommandStatus.DONE, CommandStatus.FAILED)
        device.refresh_from_db()
        assert device.info.startswith("Ver 8.0.4")


@pytest.mark.django_db
def test_a_locked_day_keeps_its_punches_out(device, tenant_a, make_employee, monkeypatch):
    employee = make_employee(tenant_a, 7)
    monkeypatch.setattr(locks, "period_locked", lambda pk, start, end=None: True)
    with tenant_context(tenant_a.id):
        links.link_by_code(device.branch_id)
    _call(tenant_a, "cdata", body="7\t2026-10-05 08:58:12\t0\t1\n", table="ATTLOG")
    with tenant_context(tenant_a.id):
        assert DevicePunch.objects.count() == 1 and not Punch.objects.filter(
            employee=employee).exists()


@pytest.mark.django_db
def test_unknown_devices_and_other_clients_are_refused(device, tenant_a, tenant_b):
    assert _call(tenant_b, "cdata").status_code == 403  # not this client's device
    refused = _call(tenant_a, "cdata", SN="NOPE")
    assert refused.status_code == 403 and refused.content == b"UNKNOWN DEVICE\n"
    TenantFeature.objects.filter(tenant=tenant_a, key="zk_devices").update(enabled=False)
    features.forget(tenant_a.pk)
    assert _call(tenant_a, "cdata").status_code == 403  # devices switched off
    _switch_on(tenant_b)
    with tenant_context(tenant_b.id), pytest.raises(ValidationError) as taken:
        devices.save_device(devices.DeviceInput(SERIAL.lower(), "Theirs",
                                                  Branch.objects.get(code=1).pk))
    assert "serial" in taken.value.fields  # one company per device


@pytest.mark.django_db
def test_the_pages_and_the_api(tenant_a, make_employee, make_member):
    from conftest import login

    _switch_on(tenant_a)
    employee = make_employee(tenant_a, 7)
    client = login(tenant_a, language="en")
    with tenant_context(tenant_a.id):
        branch = Branch.objects.get(code=1)
    made = client.post("/api/web/devices/devices/", {"serial": SERIAL, "name": "Gate",
                                                    "branch_id": branch.pk},
                       content_type="application/json")
    assert made.status_code == 201
    pk = made.json()["id"]
    _call(tenant_a, "cdata", body="7\t2026-10-05 08:58:12\t0\t1\n", table="ATTLOG")
    with tenant_context(tenant_a.id):
        pin = DeviceUser.objects.get(pin="7")
    linked = client.post(f"/api/web/devices/device-users/{pin.pk}/link/",
                         {"employee_id": employee.pk}, content_type="application/json")
    assert linked.status_code == 200
    asked = client.post(f"/api/web/devices/devices/{pk}/ask/", {"kind": "pull_users"},
                        content_type="application/json")
    assert asked.status_code == 201
    for path in ("/attendance/devices/", f"/attendance/devices/{pk}/",
                 "/reports/device_punches/?date_from=2026-10-01&date_to=2026-10-31"):
        page = client.get(path)
        assert page.status_code == 200, path
    assert "Employee 7" in client.get(f"/attendance/devices/{pk}/").content.decode()
    make_member(tenant_a, "viewer", "viewer")
    viewer = login(tenant_a, "viewer")
    assert viewer.get("/attendance/devices/").status_code == 200  # may see, not change
    assert viewer.post(f"/api/web/devices/devices/{pk}/ask/", {"kind": "test"},
                       content_type="application/json").status_code == 403
