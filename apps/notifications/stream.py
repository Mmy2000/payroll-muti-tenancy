"""The live stream of one member's notifications, as Server-Sent Events.

A stream holds no database connection while it waits. When the Hub rings it reads what is new,
in the tenant's context, and sends it. A comment now and then keeps proxies from closing it, and
it ends after a while: the browser reconnects at once and that passes the sign-in checks again,
so a suspended member can't keep listening. `Last-Event-ID` lets it pick up where it was.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from asgiref.sync import sync_to_async
from django.db import connections

from apps.core.tenancy import tenant_context

from . import services
from .present import item
from .realtime import hub

HEARTBEAT_SECONDS = 25
LIFETIME_SECONDS = 30 * 60
RETRY_MS = 3000
LATEST = 20  # after a long gap the rest is on the page, not in pop-ups


@dataclass
class Snapshot:
    unread: int
    items: list = field(default_factory=list)
    last_id: int = 0


def snapshot(tenant_id: int, member_id: int, after: int | None) -> Snapshot:
    """What the member has after notification `after`, newest last (None: nothing to send yet,
    only where things stand)."""
    from apps.iam.models import Membership

    with tenant_context(tenant_id):
        member = Membership.objects.filter(pk=member_id).first()
        if member is None:
            return Snapshot(unread=0, last_id=after or 0)
        rows = services.for_member(member)
        unread = services.unread_count(member)
        if after is None:
            newest = rows.order_by("-id").values_list("id", flat=True).first()
            return Snapshot(unread=unread, last_id=newest or 0)
        new = list(rows.filter(id__gt=after).order_by("-id")[:LATEST])[::-1]
        return Snapshot(unread=unread, items=[item(row) for row in new],
                        last_id=new[-1].pk if new else after)


def _in_a_thread(tenant_id: int, member_id: int, after: int | None) -> Snapshot:
    try:
        return snapshot(tenant_id, member_id, after)
    finally:
        connections.close_all()  # a stream must not keep a connection while it waits


def frame(event: str, data: dict, *, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def events(tenant_id: int, member_id: int, after: int | None, *, source=None,
                 load: Callable = _in_a_thread, lifetime: float = LIFETIME_SECONDS,
                 heartbeat: float = HEARTBEAT_SECONDS) -> AsyncIterator[str]:
    source = source or hub
    read = sync_to_async(load, thread_sensitive=False)
    subscription = source.subscribe(tenant_id, member_id)  # first, so nothing slips between
    try:
        state = await read(tenant_id, member_id, after)
        yield f"retry: {RETRY_MS}\n\n"
        yield frame("unread", {"unread": state.unread})
        for notice in state.items:
            yield frame("notification", notice, event_id=notice["id"])
        last_id = state.last_id
        ends = time.monotonic() + lifetime
        while (left := ends - time.monotonic()) > 0:
            if not await subscription.wait(min(heartbeat, left)):
                yield ": still here\n\n"
                continue
            state = await read(tenant_id, member_id, last_id)
            for notice in state.items:
                yield frame("notification", notice, event_id=notice["id"])
            yield frame("unread", {"unread": state.unread})
            last_id = state.last_id
    finally:
        source.unsubscribe(tenant_id, member_id, subscription)
