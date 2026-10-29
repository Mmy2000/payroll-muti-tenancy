"""Fingerprint devices (ZKTeco, ADMS "push": apps/devices/protocol.py), PayRole's `zkk.ZkDevice`,
`ZkUser`, `ZkPunch` and `ZkCommand`.

* `Device`: a device of a branch, known by its serial number. The serial is unique across every
  client: a device answers to one company only.
* `DeviceUser`: a person enrolled on the branch's devices (their PIN), linked to an employee.
  The devices of one branch share their users, as in PayRole.
* `DevicePunch`: what a device sent, exactly, never changed. A punch of a linked user also
  becomes an attendance punch (`punch`, append-only); one of an unknown or unlinked PIN waits
  until the PIN is linked, and one on days an approved payroll covers stays out.
* `DeviceCommand`: something asked of a device, picked up on its next call.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class Device(TenantScopedModel):
    serial = models.CharField(max_length=32)
    name = models.CharField(max_length=60)
    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_ip = models.CharField(max_length=45, blank=True)
    info = models.CharField(max_length=200, blank=True)  # what the device last said about itself
    resend_all = models.BooleanField(default=False)  # ask for every punch it holds, once

    class Meta:
        ordering = ["branch__code", "name"]
        constraints = [
            # Across every client: the device's calls carry nothing else to tell them apart.
            models.UniqueConstraint(fields=["serial"], name="devices_device_serial_uniq"),
            models.UniqueConstraint(fields=["tenant", "name"], name="devices_device_name_uniq"),
        ]

    def __str__(self):
        return f"{self.name} ({self.serial})"


class DeviceUser(TenantScopedModel):
    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="+")
    pin = models.CharField(max_length=24)
    name = models.CharField(max_length=60, blank=True)  # as enrolled on the device
    employee = models.ForeignKey("employees.Employee", null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="device_users")
    removed = models.BooleanField(default=False)  # no longer on the devices (kept: has punches)

    class Meta:
        ordering = ["branch__code", "pin"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "branch", "pin"],
                                    name="devices_user_pin_uniq"),
        ]

    def __str__(self):
        return f"{self.pin} {self.name}"


class DevicePunch(TenantScopedModel):
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="punches")
    device_user = models.ForeignKey(DeviceUser, on_delete=models.PROTECT, related_name="punches")
    at = models.DateTimeField()  # the device's local time, in the client's time zone
    status = models.SmallIntegerField(default=0)  # protocol.PUNCH_STATUS
    verify = models.SmallIntegerField(default=0)  # fingerprint, card, password…
    workcode = models.CharField(max_length=24, blank=True)
    punch = models.ForeignKey("attendance.Punch", null=True, blank=True,
                              on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "device", "device_user", "at"],
                                    name="devices_punch_moment_uniq"),
        ]
        indexes = [models.Index(fields=["tenant", "device_user", "punch"],
                                name="devices_punch_waiting_idx")]


class CommandStatus(models.TextChoices):
    PENDING = "pending", _("Waiting for the device")
    SENT = "sent", _("Sent to the device")
    DONE = "done", _("Done")
    FAILED = "failed", _("Failed")
    EXPIRED = "expired", _("The device didn't answer")


class DeviceCommand(TenantScopedModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="commands")
    command = models.CharField(max_length=200)
    status = models.CharField(max_length=8, choices=CommandStatus.choices,
                              default=CommandStatus.PENDING)
    result = models.IntegerField(null=True, blank=True)  # the device's Return code
    rows = models.PositiveIntegerField(default=0)  # what it sent back (users, punches)
    sent_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "device", "status"],
                                name="devices_command_status_idx")]
