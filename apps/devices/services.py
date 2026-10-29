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
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.attendance.models import Punch, PunchSource
from apps.core import locks
from apps.core.errors import Conflict, DomainError, NotFound, ValidationError
from apps.employees.models import Employee

from . import protocol
from .models import CommandStatus, Device, DeviceCommand, DevicePunch, DeviceUser

VIEW, MANAGE = "devices.device.view", "devices.device.manage"


def _invalid(fields: dict) -> ValidationError:
    return ValidationError(_("Please correct the highlighted fields."), fields=fields)


def visible_devices(actor, code: str = VIEW):
    devices = Device.objects.select_related("branch")
    branches = actor.branch_ids(code) if actor is not None else None
    return devices if branches is None else devices.filter(branch_id__in=branches)


def is_online(device: Device) -> bool:
    return bool(device.last_seen_at and timezone.now() - device.last_seen_at
                < timedelta(seconds=protocol.ONLINE_SECONDS))


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
            raise _invalid(errors)
        device.serial, device.name, device.branch_id = serial, name, data.branch_id
        device.is_active = data.is_active
        device.updated_by = getattr(actor, "user", None)
        if device.pk is None:
            device.created_by = device.updated_by
        try:
            with transaction.atomic():
                device.save()
        except IntegrityError:
            raise _invalid({"serial": [_("This serial number is already registered, here or "
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


def device_for(serial: str) -> Device | None:
    """An active device of the host's client, by its serial."""
    return Device.objects.select_for_update().filter(serial=serial.strip().upper(),
                                                     is_active=True).first()


def seen(device: Device, *, ip: str | None = None, info: str = "") -> None:
    device.last_seen_at = timezone.now()
    if ip:
        device.last_ip = ip
    fields = ["last_seen_at", "last_ip"]
    if info:
        device.info = info[:200]
        fields.append("info")
    device.save(update_fields=fields)


def handshake(device: Device) -> str:
    offset = timezone.localtime().utcoffset() or timedelta()
    text = protocol.options(device.serial, resend_all=device.resend_all,
                            utc_offset_hours=round(offset.total_seconds() / 3600))
    if device.resend_all:
        device.resend_all = False
        device.save(update_fields=["resend_all"])
    return text


def _users_by_pin(branch_id: int, pins) -> dict[str, DeviceUser]:
    users = {u.pin: u for u in DeviceUser.objects.filter(branch_id=branch_id, pin__in=set(pins))}
    for pin in set(pins) - set(users):
        users[pin] = DeviceUser.objects.create(branch_id=branch_id, pin=pin)
    return users


def receive_punches(device: Device, records: list[protocol.AttRecord]) -> int:
    """Keep what the device sent (again: the same moment twice is one punch) and bring linked
    users' punches into attendance. Returns how many records were read."""
    if not records:
        return 0
    zone = timezone.get_current_timezone()
    users = _users_by_pin(device.branch_id, [r.pin for r in records])
    DevicePunch.objects.bulk_create([
        DevicePunch(device=device, device_user=users[r.pin], status=r.status, verify=r.verify,
                    workcode=r.workcode, at=timezone.make_aware(r.at, zone))
        for r in records], ignore_conflicts=True)
    for user in {u.pk: u for u in users.values() if u.employee_id}.values():
        to_attendance(user)
    _count_rows(device, protocol.PULL_PUNCHES, len(records))
    return len(records)


def to_attendance(user: DeviceUser) -> int:
    """The user's waiting punches become the employee's attendance punches, but on days an
    approved payroll covers, and outside their employment."""
    employee = user.employee
    if employee is None:
        return 0
    moved = 0
    for record in DevicePunch.objects.filter(device_user=user, punch__isnull=True).order_by("at"):
        day = timezone.localtime(record.at).date()
        if day < employee.hired_on or (employee.left_on and day > employee.left_on) \
                or locks.period_locked(employee.pk, day):
            continue
        punch, _created = Punch.objects.get_or_create(
            employee=employee, at=record.at, defaults={"source": PunchSource.DEVICE})
        record.punch = punch
        record.save(update_fields=["punch", "updated_at"])
        moved += 1
    return moved


def receive_users(device: Device, users: dict[str, str]) -> int:
    """The device's list of users: new PINs are added, names kept up to date, and PINs that are
    gone are marked removed once a full list arrives (an answer to "pull users")."""
    known = _users_by_pin(device.branch_id, users)
    for pin, name in users.items():
        user = known[pin]
        if (name and user.name != name) or user.removed:
            user.name, user.removed = name or user.name, False
            user.save(update_fields=["name", "removed", "updated_at"])
    pulling = DeviceCommand.objects.filter(device=device, status=CommandStatus.SENT,
                                           command=protocol.PULL_USERS).exists()
    if pulling and users:
        for user in DeviceUser.objects.filter(branch_id=device.branch_id, removed=False).exclude(
                pin__in=users):
            if user.punches.exists():
                user.removed = True
                user.save(update_fields=["removed", "updated_at"])
            else:
                user.delete()
    _count_rows(device, protocol.PULL_USERS, len(users))
    return len(users)


def _count_rows(device: Device, command_prefix: str, rows: int) -> None:
    """Rows sent back for a command the device is answering (its latest sent one of the kind;
    PayRole added every realtime push to it too, so only commands sent are counted)."""
    command = (DeviceCommand.objects.filter(device=device, status=CommandStatus.SENT,
                                            command__startswith=command_prefix)
               .order_by("-sent_at").first())
    if command is not None:
        command.rows += rows
        command.save(update_fields=["rows", "updated_at"])


def next_commands(device: Device) -> list[tuple[int, str]]:
    """The oldest waiting command, marked sent (one at a time: PayRole sent them all at once)."""
    expire_commands(device)
    command = (DeviceCommand.objects.select_for_update()
               .filter(device=device, status=CommandStatus.PENDING).order_by("created_at").first())
    if command is None:
        return []
    command.status, command.sent_at = CommandStatus.SENT, timezone.now()
    command.save(update_fields=["status", "sent_at", "updated_at"])
    return [(command.pk, command.command)]


def record_replies(device: Device, replies: list[protocol.CommandReply]) -> int:
    done = 0
    for reply in replies:
        command = DeviceCommand.objects.filter(device=device, pk=reply.id).first()
        if command is None or command.status != CommandStatus.SENT:
            continue
        command.status = CommandStatus.DONE if reply.ok else CommandStatus.FAILED
        command.result, command.done_at = reply.result, timezone.now()
        command.save(update_fields=["status", "result", "done_at", "updated_at"])
        done += 1
    return done


def expire_commands(device: Device | None = None) -> int:
    """Commands the device never picked up or never answered (PayRole only expired them while
    a screen was watching)."""
    now = timezone.now()
    commands = DeviceCommand.objects.all() if device is None else device.commands.all()
    late = (commands.filter(status=CommandStatus.PENDING,
                            created_at__lt=now - timedelta(seconds=protocol.PICKUP_SECONDS))
            .update(status=CommandStatus.EXPIRED, done_at=now))
    late += (commands.filter(status=CommandStatus.SENT,
                             sent_at__lt=now - timedelta(seconds=protocol.REPLY_SECONDS))
             .update(status=CommandStatus.EXPIRED, done_at=now))
    return late


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
            raise _invalid({"start": [_("Enter the days to pull, first day first.")]})
        text = protocol.pull_punches(data.start, data.end)
    elif data.kind in (TEST, PULL_USERS):
        text = protocol.INFO if data.kind == TEST else protocol.PULL_USERS
    else:
        raise _invalid({"kind": [_("Choose what to ask.")]})
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


def link(device_user_id: int, employee_id: int | None, *, actor=None) -> DeviceUser:
    """Link a PIN to an employee of the same branch (or unlink it). Once its punches are in
    someone's attendance the link stays: correct those days with attendance entries."""
    with transaction.atomic():
        user = DeviceUser.objects.select_for_update().filter(pk=device_user_id).first()
        if user is None or (actor is not None
                            and not actor.can(MANAGE, branch=user.branch_id)):
            raise NotFound(_("Not found."))
        if user.employee_id == employee_id:
            return user
        if user.punches.filter(punch__isnull=False).exists():
            raise DomainError(_("This PIN's punches are already in an employee's attendance: "
                                "the link can't change."), code="DEVICES_LINK_USED")
        employee = None
        if employee_id is not None:
            employee = Employee.objects.filter(pk=employee_id, branch_id=user.branch_id).first()
            if employee is None:
                raise _invalid({"employee_id": [_("Choose an employee of the device's "
                                                  "branch.")]})
            if DeviceUser.objects.filter(branch_id=user.branch_id, employee=employee).exclude(
                    pk=user.pk).exists():
                raise _invalid({"employee_id": [_("This employee already has a PIN on this "
                                                  "branch's devices.")]})
        user.employee = employee
        user.updated_by = getattr(actor, "user", None)
        user.save(update_fields=["employee", "updated_by", "updated_at"])
        to_attendance(user)
    return user


def link_by_code(branch_id: int, *, actor=None) -> int:
    """Link every unlinked PIN that is an employee's code in the branch (PayRole auto_link).
    Returns how many were linked."""
    if actor is not None:
        actor.require(MANAGE, branch=branch_id)
    linked = 0
    with transaction.atomic():
        taken = set(DeviceUser.objects.filter(branch_id=branch_id, employee__isnull=False)
                    .values_list("employee_id", flat=True))
        people = {str(e.code): e for e in Employee.objects.filter(
            branch_id=branch_id, left_on__isnull=True).exclude(pk__in=taken)}
        for user in DeviceUser.objects.select_for_update().filter(branch_id=branch_id,
                                                                  employee__isnull=True):
            employee = people.pop(user.pin.lstrip("0") or "0", None)
            if employee is not None:
                user.employee = employee
                user.save(update_fields=["employee", "updated_at"])
                to_attendance(user)
                linked += 1
    return linked
