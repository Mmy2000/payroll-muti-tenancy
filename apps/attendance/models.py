"""Attendance: what happened each work day, and the leave and hourly permissions that explain an
absence.

* `Punch`: a raw clock event from a device, the mobile app or an Excel file. Append-only: it is
  never edited or deleted, so what the clock said stays on record.
* `AttendanceDay`: a manager's entry for one employee and one work day. It wins over the punches
  of that day without touching them (PayRole deleted the device rows instead: zkk/signals.py).
* `LeaveRequest` / `HourlyLeave`: days and hours away, approved or not.

A day's status (present, absent, day off, holiday, leave…) is not stored: it is worked out from
these and the employee's schedule (apps.attendance.domain.days), the same way for the screens
and for payroll. PayRole wrote `Attendance_Off` rows during payroll instead.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class PunchSource(models.TextChoices):
    IMPORT = "import", _("Excel import")
    DEVICE = "device", _("Fingerprint device")
    MOBILE = "mobile", _("Mobile app")
    API = "api", _("External system")


class PunchDirection(models.IntegerChoices):  # the mobile app's "status"
    IN = 0, _("In")
    OUT = 1, _("Out")


class Punch(TenantScopedModel):
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="punches")
    at = models.DateTimeField()
    source = models.CharField(max_length=8, choices=PunchSource.choices)
    # What the employee said it was (the mobile app); a device's key is not trusted: the day's
    # first and last punches are its in and out either way.
    direction = models.PositiveSmallIntegerField(choices=PunchDirection.choices, null=True,
                                                 blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["at"]
        constraints = [
            # The same moment twice is one punch, whichever source sent it again.
            models.UniqueConstraint(fields=["tenant", "employee", "at"],
                                    name="attendance_punch_moment_uniq"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.at:%Y-%m-%d %H:%M}"


class DayKind(models.TextChoices):
    WORKED = "worked", _("Worked")
    ABSENT = "absent", _("Absent")
    EXCUSED = "excused", _("Excused absence")
    DAY_OFF = "day_off", _("Day off")


class AttendanceDay(TenantScopedModel):
    """A manager's word on one work day. `worked` carries the times; the other kinds none.
    `excused` is an absence accepted after the fact: not penalized, not paid (paid days away are
    leave of a paid type). `day_off` makes a working day a rest day; if the employee clocks in
    anyway, the day is worked on a rest day."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="attendance_days")
    work_date = models.DateField()
    kind = models.CharField(max_length=8, choices=DayKind.choices)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-work_date"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "employee", "work_date"],
                                    name="attendance_day_uniq"),
            models.CheckConstraint(
                condition=(Q(kind="worked", check_in__isnull=False)
                           | (~Q(kind="worked") & Q(check_in__isnull=True,
                                                     check_out__isnull=True))),
                name="attendance_day_times_check"),
            models.CheckConstraint(
                condition=Q(check_out__isnull=True) | Q(check_out__gt=models.F("check_in")),
                name="attendance_day_order_check"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.work_date} {self.kind}"


# --- requests that are approved or not ----------------------------------------------------


class RequestStatus(models.TextChoices):
    PENDING = "pending", _("Waiting for approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")


class ApprovableRequest(TenantScopedModel):
    """A request whose status moves through apps.attendance.services.approvals (pending →
    approved or
    rejected; pending or approved → cancelled)."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="+")
    status = models.CharField(max_length=10, choices=RequestStatus.choices,
                              default=RequestStatus.PENDING)
    reason = models.CharField(max_length=300, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        abstract = True


class LeaveType(TenantScopedModel):
    """A kind of leave. PayRole knew only annual leave; here the client keeps a list (annual,
    sick, unpaid…), each paid or not, and counted against the yearly balance or not."""

    code = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    paid = models.BooleanField(default=True)
    uses_annual_balance = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"],
                                    name="attendance_leavetype_code_uniq"),
            models.UniqueConstraint(fields=["tenant", "name"],
                                    name="attendance_leavetype_name_uniq"),
        ]

    def __str__(self):
        return self.name


class LeaveRequest(ApprovableRequest):
    """Days away (PayRole: `zkk.Pfg1`). `days` counts the working days in the range when the
    request was made: weekly days off and public holidays don't use leave."""

    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="+")
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["-start_date", "-id"]
        indexes = [models.Index(fields=["tenant", "employee", "start_date"],
                                name="attendance_leave_emp_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")),
                                   name="attendance_leave_range_check"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.start_date}–{self.end_date}"


class HourlyLeave(ApprovableRequest):
    """Hours away within a work day (PayRole: `zkk.Pfg2`, "إذن"). The minutes are not deducted
    from pay, up to the employee's monthly allowance (Compensation.permission_hours)."""

    work_date = models.DateField()
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    minutes = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["-work_date", "-id"]
        indexes = [models.Index(fields=["tenant", "employee", "work_date"],
                                name="attendance_hourly_emp_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(minutes__gt=0),
                                   name="attendance_hourly_minutes_check"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.work_date} {self.starts_at}–{self.ends_at}"
