"""Fingerprint devices: setting them up, what they send, and what they are asked to do.

What a device sends is kept as it came (`DevicePunch`). A punch whose PIN is linked to an
employee also becomes an attendance punch (source "device"), judged like any other clock time;
the device's own in/out key is not trusted (PayRole ignored it too). A PIN linked later brings
its waiting punches in. Days an approved payroll covers are left alone: their punches are kept,
but stay out of attendance.

Permissions: `devices.device.view` and `devices.device.manage`, by the device's branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, NotFound, invalid_fields

from .. import protocol
from ..models import CommandStatus, Device, DeviceCommand
from ..permissions import MANAGE
from ..selectors import visible_devices

# --- devices -------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceInput:
    serial: str
    name: str
    branch_id: int
    is_active: bool = True


def save_device(data: DeviceInput, *, device_id: int | None = None, actor=None) -> Device:
    serial, name = data.serial.strip().upper(), data.name.strip()
    if actor is not None:
        actor.require(MANAGE, branch=data.branch_id)
    with transaction.atomic():
        device = Device() if device_id is None else \
            visible_devices(actor, MANAGE).select_for_update().filter(pk=device_id).first()
        if device is None:
            raise NotFound(_("Not found."))
        errors = {}
        if not serial:
            errors["serial"] = [_("Enter the serial number shown on the device.")]
        if not name:
            errors["name"] = [_("Enter a name.")]
        elif Device.objects.filter(name=name).exclude(pk=device.pk).exists():
            errors["name"] = [_("Another device has this name.")]
        if device.pk and device.branch_id != data.branch_id and device.punches.exists():
            errors["branch_id"] = [_("The device has punches: it stays in its branch.")]
        if errors:
            raise invalid_fields(errors)
        device.serial, device.name, device.branch_id = serial, name, data.branch_id
        device.is_active = data.is_active
        device.updated_by = getattr(actor, "user", None)
        if device.pk is None:
            device.created_by = device.updated_by
        try:
            with transaction.atomic():
                device.save()
        except IntegrityError:
            raise invalid_fields({"serial": [_("This serial number is already registered, here or "
                                         "with another company.")]}) from None
    return device


def resend_all(device_id: int, *, actor=None) -> Device:
    """Ask the device for every punch it holds on its next handshake (after a restart)."""
    with transaction.atomic():
        device = visible_devices(actor, MANAGE).select_for_update().filter(pk=device_id).first()
        if device is None:
            raise NotFound(_("Not found."))
        device.resend_all = True
        device.save(update_fields=["resend_all", "updated_at"])
    return device


# --- the device's calls ---------------------------------------------------------------------


# --- commands asked from the screens --------------------------------------------------------

TEST, PULL_USERS, PULL_PUNCHES = "test", "pull_users", "pull_punches"


@dataclass(frozen=True)
class CommandInput:
    kind: str
    start: date | None = None
    end: date | None = None


def ask(device_id: int, data: CommandInput, *, actor=None) -> DeviceCommand:
    if data.kind == PULL_PUNCHES:
        if data.start is None or data.end is None or data.end < data.start:
            raise invalid_fields({"start": [_("Enter the days to pull, first day first.")]})
        text = protocol.pull_punches(data.start, data.end)
    elif data.kind in (TEST, PULL_USERS):
        text = protocol.INFO if data.kind == TEST else protocol.PULL_USERS
    else:
        raise invalid_fields({"kind": [_("Choose what to ask.")]})
    with transaction.atomic():
        device = visible_devices(actor, MANAGE).filter(pk=device_id).first()
        if device is None:
            raise NotFound(_("Not found."))
        if actor is not None:
            actor.require(MANAGE, branch=device.branch_id)
        if device.commands.filter(status__in=(CommandStatus.PENDING, CommandStatus.SENT),
                                  command=text).exists():
            raise Conflict(_("The same request is already waiting for the device."),
                           code="DEVICES_COMMAND_WAITING")
        return DeviceCommand.objects.create(device=device, command=text,
                                            requested_by=getattr(actor, "user", None))


# --- linking PINs to employees --------------------------------------------------------------


