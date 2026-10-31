"""What a device says over the iClock protocol (protocol.py parses it), and what it is told."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.attendance.models import Punch, PunchSource
from apps.core import locks

from .. import protocol
from ..models import CommandStatus, Device, DeviceCommand, DevicePunch, DeviceUser


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
