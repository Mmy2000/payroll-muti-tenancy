"""The fingerprint devices: which ones, and how they are doing."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.employees.selectors import visible_employees
from apps.org.selectors import active_branches

from . import protocol
from .models import Device, DeviceUser
from .permissions import MANAGE, VIEW

RECENT = 50


def visible_devices(actor, code: str = VIEW):
    devices = Device.objects.select_related("branch")
    branches = actor.branch_ids(code) if actor is not None else None
    return devices if branches is None else devices.filter(branch_id__in=branches)


def find_device(actor, pk, code: str = VIEW) -> Device | None:
    return visible_devices(actor, code).filter(pk=pk).first()


def is_online(device: Device) -> bool:
    return bool(device.last_seen_at and timezone.now() - device.last_seen_at
                < timedelta(seconds=protocol.ONLINE_SECONDS))


def device_for(serial: str) -> Device | None:
    """An active device of the host's client, by its serial."""
    return Device.objects.select_for_update().filter(serial=serial.strip().upper(),
                                                     is_active=True).first()


def no_device_users():
    """The API schema reads the model of `id` from this."""
    return DeviceUser.objects.none()


def users_of_branch(branch):
    return (DeviceUser.objects.filter(branch=branch).select_related("employee")
            .order_by("removed", "pin"))


def recent_commands(device: Device):
    return device.commands.select_related("requested_by")[:10]


def recent_punches(device: Device):
    return device.punches.select_related("device_user__employee")[:RECENT]


def linkable_employees(actor, branch):
    return visible_employees(actor, MANAGE).filter(branch=branch, left_on__isnull=True).order_by(
        "code")


def branch_choices(allowed):
    """The active branches, by code, of `allowed` (None = all of them)."""
    branches = active_branches().order_by("code")
    return branches if allowed is None else branches.filter(pk__in=allowed)
