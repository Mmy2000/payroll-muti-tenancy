"""Telling open browsers that something changed for a member, across every server process.

PostgreSQL carries it: `announce` is a NOTIFY, delivered only when the transaction commits, so a
rolled-back action announces nothing, and no other service is needed. It says who, never what:
a stream reads the text itself, through the tenant's row-level security.

`Hub` is the one LISTEN connection of a process, handing each announcement to the streams open
for that member (Observer). It lives in its own thread, which suits any server and event loop
(psycopg's async mode can't run on Windows' default loop).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterable

import psycopg
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connection
from psycopg.conninfo import make_conninfo

logger = logging.getLogger(__name__)
CHANNEL = "payroll_notifications"
RETRY_SECONDS = 5


def announce(tenant_id: int, member_ids: Iterable[int]) -> None:
    """Call in the transaction that made the change. Repeats within it arrive once."""
    with connection.cursor() as cursor:
        for member_id in member_ids:
            cursor.execute("SELECT pg_notify(%s, %s)",
                           [CHANNEL, json.dumps({"t": tenant_id, "m": member_id})])


class Subscription:
    """One open stream's doorbell: rung from the Hub's thread, awaited on the stream's loop."""

    def __init__(self):
        self._loop = asyncio.get_running_loop()
        self._rung = asyncio.Event()

    def ring(self) -> None:
        self._loop.call_soon_threadsafe(self._rung.set)

    async def wait(self, timeout: float) -> bool:
        """True when rung, False when `timeout` seconds passed quietly."""
        try:
            await asyncio.wait_for(self._rung.wait(), timeout)
        except TimeoutError:
            return False
        self._rung.clear()
        return True


class Hub:
    def __init__(self, conninfo: str = ""):
        self.conninfo = conninfo
        self._lock = threading.Lock()
        self._subscribers: dict[tuple[int, int], set[Subscription]] = defaultdict(set)
        self._thread: threading.Thread | None = None

    def subscribe(self, tenant_id: int, member_id: int) -> Subscription:
        subscription = Subscription()
        with self._lock:
            self._subscribers[(tenant_id, member_id)].add(subscription)
            if self._thread is None:
                self._thread = threading.Thread(target=self._listen, name="notifications-hub",
                                                daemon=True)
                self._thread.start()
        return subscription

    def unsubscribe(self, tenant_id: int, member_id: int, subscription: Subscription) -> None:
        with self._lock:
            found = self._subscribers.get((tenant_id, member_id))
            if found is not None:
                found.discard(subscription)
                if not found:
                    del self._subscribers[(tenant_id, member_id)]

    def deliver(self, payload: str) -> None:
        """An announcement arrived: ring its member's streams."""
        try:
            data = json.loads(payload)
            key = (data["t"], data["m"])
        except (ValueError, KeyError, TypeError):
            logger.warning("Bad notification announcement: %r", payload)
            return
        with self._lock:
            found = list(self._subscribers.get(key, ()))
        for subscription in found:
            subscription.ring()

    def _ring_everyone(self) -> None:
        with self._lock:
            found = [s for group in self._subscribers.values() for s in group]
        for subscription in found:
            subscription.ring()

    def _listen(self) -> None:
        """For the life of the process. After a lost connection the streams catch up from the
        database, so an announcement missed meanwhile only arrives a little late."""
        while True:
            try:
                with psycopg.connect(self.conninfo or _conninfo(), autocommit=True) as listener:
                    listener.execute(f"LISTEN {CHANNEL}")
                    self._ring_everyone()
                    for notice in listener.notifies():
                        self.deliver(notice.payload)
            except psycopg.Error as error:
                logger.warning("Notifications listener lost: %s", error)
            time.sleep(RETRY_SECONDS)


def _conninfo() -> str:
    db = settings.DATABASES[DEFAULT_DB_ALIAS]
    return make_conninfo(**{key: str(value) for key, value in {
        "dbname": db.get("NAME"), "user": db.get("USER"), "password": db.get("PASSWORD"),
        "host": db.get("HOST"), "port": db.get("PORT")}.items() if value})


hub = Hub()
