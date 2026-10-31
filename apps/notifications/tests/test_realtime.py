"""Notifications: domain events decouple the services, and the stream delivers them live."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.attendance.events import LeaveRequested
from apps.core import events as bus
from apps.core.events import Event, publish, subscribe
from apps.core.tenancy import tenant_context
from apps.notifications import realtime, services, stream
from apps.notifications.kinds import LOOKS, look
from apps.notifications.models import Kind, Notification
from apps.notifications.present import item
from apps.notifications.realtime import Hub
from apps.notifications.stream import Snapshot, frame, snapshot
from conftest import login

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[3]


def _owner(tenant):
    from apps.iam.models import Membership

    return Membership.objects.get(username="owner")


# --- domain events ---------------------------------------------------------------------------


def test_a_service_does_not_know_about_notifications():
    """Dependencies point one way: notifications listens to the services, never the reverse."""
    for path in (ROOT / "apps").rglob("*.py"):
        part = path.relative_to(ROOT).parts[1]
        if part in ("notifications", "core", "mobile") or "tests" in path.parts:
            continue  # core's context processor and the app's API read notifications
        source = path.read_text(encoding="utf-8")
        assert "apps.notifications" not in source or "notifications.selectors" in source, path


def test_publishing_reaches_every_subscriber_and_only_for_its_event():
    class Happened(Event):
        pass

    class Other(Event):
        pass

    seen = []
    subscribe(Happened)(lambda event: seen.append("first"))
    subscribe(Happened)(lambda event: seen.append("second"))
    publish(Other())
    assert seen == []
    publish(Happened())
    assert seen == ["first", "second"]
    bus._handlers.pop(Happened)


def test_a_published_event_notifies(tenant_a, make_employee):
    from apps.attendance.models import LeaveRequest, LeaveType
    from apps.mobile.services import access
    from conftest import PASSWORD

    employee = make_employee(tenant_a, 1, name="Mona")
    with tenant_context(tenant_a.id):
        member = access.give_login(employee.pk, "mona", PASSWORD)
        employee.refresh_from_db()
        request = LeaveRequest.objects.create(
            employee=employee, leave_type=LeaveType.objects.first(), days=1,
            start_date="2026-11-02", end_date="2026-11-02")
        publish(LeaveRequested(request=request, by=member))
        told = Notification.objects.get(kind=Kind.LEAVE_REQUEST)
    assert "Mona" in told.title and told.member_id != member.pk


# --- announcing ------------------------------------------------------------------------------


def test_a_notification_is_announced_with_ids_and_no_text(tenant_a):
    with tenant_context(tenant_a.id):
        owner = _owner(tenant_a)
        with CaptureQueriesContext(connection) as queries:
            services.notify([owner], Kind.MOVEMENT, "Private salary figure")
    announcement = [q["sql"] for q in queries if "pg_notify" in q["sql"]]
    assert len(announcement) == 1
    assert "Private salary figure" not in announcement[0]
    assert realtime.CHANNEL in announcement[0]


def test_reading_tells_the_members_other_tabs(tenant_a):
    with tenant_context(tenant_a.id):
        owner = _owner(tenant_a)
        services.notify([owner], Kind.MOVEMENT, "Hello")
        with CaptureQueriesContext(connection) as queries:
            assert services.mark_read(owner) == 1
        assert any("pg_notify" in q["sql"] for q in queries)
        with CaptureQueriesContext(connection) as queries:
            assert services.mark_read(owner) == 0  # nothing changed, nothing to say
        assert not any("pg_notify" in q["sql"] for q in queries)


# --- the hub ---------------------------------------------------------------------------------


def test_the_hub_rings_only_that_members_streams():
    async def scenario():
        hub = Hub()
        hub._thread = object()  # no real listener in a test
        mine = hub.subscribe(1, 10)
        same_member_other_tab = hub.subscribe(1, 10)
        other_member = hub.subscribe(1, 11)
        other_tenant = hub.subscribe(2, 10)
        hub.deliver(json.dumps({"t": 1, "m": 10}))
        await asyncio.sleep(0)
        assert await mine.wait(0.01) is True
        assert await same_member_other_tab.wait(0.01) is True
        assert await other_member.wait(0.01) is False
        assert await other_tenant.wait(0.01) is False

        hub.unsubscribe(1, 10, mine)
        hub.unsubscribe(1, 10, same_member_other_tab)
        assert (1, 10) not in hub._subscribers
        hub.deliver("not json")  # a bad announcement is ignored

    asyncio.run(scenario())


# --- the stream ------------------------------------------------------------------------------


class FakeHub:
    """Rings when told to, like the real one, with no database."""

    def __init__(self):
        self.subscription = None
        self.left = False

    def subscribe(self, tenant_id, member_id):
        self.subscription = realtime.Subscription()
        return self.subscription

    def unsubscribe(self, tenant_id, member_id, subscription):
        self.left = True


def test_the_stream_sends_what_is_new_then_ends_and_leaves():
    async def scenario():
        source = FakeHub()
        reads = iter([
            Snapshot(unread=2, last_id=5),
            Snapshot(unread=3, last_id=6, items=[{"id": 6, "title": "مرحبا"}])])
        calls = []

        def load(tenant_id, member_id, after):
            calls.append(after)
            return next(reads)

        got = []
        async for chunk in stream.events(1, 10, None, source=source, load=load, lifetime=0.2,
                                         heartbeat=0.05):
            got.append(chunk)
            if '"unread": 2' in chunk:
                source.subscription.ring()
        return got, calls, source

    got, calls, source = asyncio.run(scenario())
    joined = "".join(got)
    assert got[0].startswith("retry:")
    assert 'event: unread\ndata: {"unread": 2}' in joined
    assert "id: 6\nevent: notification" in joined and "مرحبا" in joined
    assert ": still here" in joined  # kept alive while quiet
    assert calls == [None, 5]  # the second read starts after the first
    assert source.left  # a closed stream takes its place in the hub with it


def test_a_snapshot_is_the_members_own(tenant_a, make_member):
    other = make_member(tenant_a, "clerk", "viewer")
    with tenant_context(tenant_a.id):
        owner = _owner(tenant_a)
        services.notify([owner], Kind.MOVEMENT, "For the owner")
        services.notify([other], Kind.MOVEMENT, "For the clerk")
        first = Notification.objects.get(member=owner).pk
    state = snapshot(tenant_a.id, other.pk, first - 1)
    assert [i["title"] for i in state.items] == ["For the clerk"]
    assert state.unread == 1


def test_a_snapshot_cannot_cross_tenants(tenant_a, tenant_b):
    with tenant_context(tenant_b.id):
        services.notify([_owner(tenant_b)], Kind.MOVEMENT, "Bravo's secret")
        bravo_owner = _owner(tenant_b).pk
    # Bravo's member id, read as Alpha: row-level security shows nothing.
    state = snapshot(tenant_a.id, bravo_owner, 0)
    assert state.items == [] and state.unread == 0


def test_the_first_connection_starts_from_now(tenant_a):
    with tenant_context(tenant_a.id):
        owner = _owner(tenant_a)
        services.notify([owner], Kind.MOVEMENT, "Old news")
    state = snapshot(tenant_a.id, owner.pk, None)
    assert state.items == [] and state.unread == 1 and state.last_id > 0  # not popped up again


def test_frames_are_valid_server_sent_events():
    assert frame("unread", {"unread": 1}) == 'event: unread\ndata: {"unread": 1}\n\n'
    assert frame("notification", {"id": 7}, event_id=7).startswith("id: 7\n")


def test_the_stream_needs_a_sign_in_and_an_async_server(tenant_a):
    assert Client(HTTP_HOST="alpha.localhost").get("/notifications/stream/").status_code == 401
    # The test client is not async: it says so at once, and the bell polls.
    assert login(tenant_a).get("/notifications/stream/").status_code == 503


# --- what the screens get ---------------------------------------------------------------------


def test_every_kind_has_a_look():
    assert set(LOOKS) == set(Kind)
    assert look("unknown").icon == "bell"


def test_the_panel_gets_the_time_and_the_tone(tenant_a):
    with tenant_context(tenant_a.id):
        owner = _owner(tenant_a)
        services.notify([owner], Kind.SALARY_PAID, "Your pay was paid")
        shown = item(Notification.objects.get())
    assert shown["tone"] == "positive" and shown["icon"] == "banknote"
    assert re.match(r"\d{4}-\d{2}-\d{2}T", shown["at"])
