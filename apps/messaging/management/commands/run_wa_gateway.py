"""Keeps the WhatsApp gateway (ops/wa-gateway) in line with the console's settings: started when
it is switched on, stopped when it is off, restarted when its key or address changes or it
crashes. Nothing to edit or restart by hand. A gateway on another server is left alone.

Runs all the time, in `ops/dev.py` and as one service in production, idle while WhatsApp is off.
The key reaches the gateway in its environment, never on a command line."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.utils import OperationalError

from apps.platform.tenants.models import WhatsAppService

CHECK_EVERY = 3  # seconds: a change in the console shows here within this
RESTART_AFTER = 10  # seconds after a crash, so a failing gateway doesn't spin
GATEWAY = settings.BASE_DIR / "ops" / "wa-gateway"


@dataclass(frozen=True)
class Wanted:
    key: str
    host: str
    port: int


def wanted(service: WhatsAppService) -> Wanted | None:
    """What should be running here for these settings; None for nothing."""
    if not (service.ready and service.is_local):
        return None
    address = urlsplit(service.url)
    return Wanted(service.secret, address.hostname, address.port or 80)


class Command(BaseCommand):
    help = "Run the WhatsApp gateway as the platform console says."

    def handle(self, *args, **options):
        signal.signal(signal.SIGTERM, self._terminate)
        self.child, self.running, self.said = None, None, ""
        self.retry_at = 0.0
        self.say("Following the console's WhatsApp settings.")
        try:
            while True:
                self.step()
                time.sleep(CHECK_EVERY)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    @staticmethod
    def _terminate(*_args):
        raise KeyboardInterrupt

    def say(self, text: str) -> None:
        if text != self.said:  # once, not every few seconds
            self.said = text
            self.stdout.write(text)

    def step(self) -> None:
        close_old_connections()
        try:
            goal = wanted(WhatsAppService.load())
        except OperationalError:
            self.say("The database is not reachable: trying again.")
            return
        if self.child is not None and self.child.poll() is not None:
            self.say(f"The gateway stopped (code {self.child.returncode}): starting it again.")
            self.child, self.running = None, None
            self.retry_at = time.monotonic() + RESTART_AFTER
        if goal == self.running or time.monotonic() < self.retry_at:
            return
        self.stop()
        if goal is None:
            self.say("WhatsApp is off, or its gateway is on another server: nothing to run here.")
        elif self.start(goal):
            self.running = goal

    def start(self, goal: Wanted) -> bool:
        node = shutil.which("node")
        if node is None or not (GATEWAY / "node_modules").is_dir():
            self.say("The gateway is not installed: run `npm ci` in ops/wa-gateway.")
            return False
        env = {**os.environ, "WA_GATEWAY_KEY": goal.key, "HOST": goal.host,
               "PORT": str(goal.port)}
        self.child = subprocess.Popen([node, "server.mjs"], cwd=GATEWAY, env=env)
        self.say(f"Gateway started on {goal.host}:{goal.port}.")
        return True

    def stop(self) -> None:
        if self.child is None:
            return
        self.child.terminate()
        try:
            self.child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.child.kill()
        self.child, self.running = None, None
