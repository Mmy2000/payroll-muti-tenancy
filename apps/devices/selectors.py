"""The fingerprint devices: which ones, and how they are doing."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import protocol
from .models import Device
from .permissions import VIEW


def visible_devices(actor, code: str = VIEW):
    devices = Device.objects.select_related("branch")
    branches = actor.branch_ids(code) if actor is not None else None
    return devices if branches is None else devices.filter(branch_id__in=branches)


def is_online(device: Device) -> bool:
    return bool(device.last_seen_at and timezone.now() - device.last_seen_at
                < timedelta(seconds=protocol.ONLINE_SECONDS))


def device_for(serial: str) -> Device | None:
    """An active device of the host's client, by its serial."""
    return Device.objects.select_for_update().filter(serial=serial.strip().upper(),
                                                     is_active=True).first()
