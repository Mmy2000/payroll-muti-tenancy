"""Employees, with the history of their pay and their working hours.

PayRole kept everything on one card (`Enp.Pfe1`, ~60 columns) and overwrote salary and shift
in place, so re-running an old month used today's values. Here the card holds who the person
is; `Compensation` and `WorkSchedule` are effective-dated rows, and payroll uses the row in
effect on each day.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import decrypt
from apps.core.media import TenantUploadPath, validate_image
from apps.core.models import EffectiveDatedModel, TenantScopedModel


class Gender(models.TextChoices):
    MALE = "male", _("Male")
    FEMALE = "female", _("Female")


class MaritalStatus(models.TextChoices):
    SINGLE = "single", _("Single")
    MARRIED = "married", _("Married")
    DIVORCED = "divorced", _("Divorced")
    WIDOWED = "widowed", _("Widowed")


class MilitaryStatus(models.TextChoices):
    COMPLETED = "completed", _("Completed")
    EXEMPT = "exempt", _("Exempt")
    POSTPONED = "postponed", _("Postponed")
    NOT_APPLICABLE = "na", _("Not applicable")


class Employee(TenantScopedModel):
    code = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    gender = models.CharField(max_length=6, choices=Gender.choices, blank=True)
    # Encrypted at rest; the blind index finds a duplicate without decrypting (apps.core.crypto).
    national_id_encrypted = models.TextField(blank=True)
    national_id_index = models.CharField(max_length=64, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    photo = models.FileField(upload_to=TenantUploadPath("employees"), blank=True,
                             validators=[validate_image])
    # Their own login to the mobile app (apps/mobile), if they have one.
    member = models.OneToOneField("iam.Membership", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="employee")

    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="+")
    department = models.ForeignKey("org.Department", null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    job_title = models.CharField(max_length=120, blank=True)
    hired_on = models.DateField()
    # The last day worked. PayRole: `l_date` (an employee is active while it is empty).
    left_on = models.DateField(null=True, blank=True)
    leave_reason = models.CharField(max_length=300, blank=True)

    insurance_number = models.CharField(max_length=30, blank=True)
    insured_from = models.DateField(null=True, blank=True)

    qualification = models.CharField(max_length=200, blank=True)
    marital_status = models.CharField(max_length=10, choices=MaritalStatus.choices, blank=True)
    children = models.PositiveSmallIntegerField(default=0)
    military_status = models.CharField(max_length=10, choices=MilitaryStatus.choices, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]
        indexes = [models.Index(fields=["tenant", "branch"], name="employees_branch_idx")]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="employees_code_uniq"),
            models.UniqueConstraint(fields=["tenant", "national_id_index"],
                                    condition=~Q(national_id_index=""),
                                    name="employees_national_id_uniq"),
            models.CheckConstraint(condition=Q(left_on__isnull=True)
                                   | Q(left_on__gte=models.F("hired_on")),
                                   name="employees_left_after_hired_check"),
        ]

    def __str__(self):
        return self.name

    @property
    def national_id(self) -> str:
        return decrypt(self.national_id_encrypted) if self.national_id_encrypted else ""

    @property
    def is_active(self) -> bool:
        return self.left_on is None or self.left_on >= timezone.localdate()


class WageType(models.TextChoices):
    FIXED = "fixed", _("Fixed salary")
    DAILY = "daily", _("Daily wage")
    HOURLY = "hourly", _("Hourly wage")


class PayFrequency(models.TextChoices):
    MONTHLY = "monthly", _("Monthly")
    BIWEEKLY = "biweekly", _("Every two weeks")
    WEEKLY = "weekly", _("Weekly")


class Compensation(EffectiveDatedModel):
    """What the employee is paid from `effective_from` on (PayRole: `Pfe1.type`, `sal`,
    `d_sal`, `h_sal`, `hour`, `val_ovr`, `dis_hol`, `val_hol`, `i_net`, `hol`, `perm`).

    The wage type (how pay is counted) and the pay frequency (how often it is run) are separate
    (docs/payroll-design.md §1). `salary` is one unit of the wage type: the salary of one pay
    period, the day's wage or the hour's wage. The day and hour rates follow from it
    (apps.employees.domain.rates.PayTerms)."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="pay_history")
    wage_type = models.CharField(max_length=8, choices=WageType.choices, default=WageType.FIXED)
    pay_frequency = models.CharField(max_length=8, choices=PayFrequency.choices,
                                     default=PayFrequency.MONTHLY)
    salary = models.DecimalField(max_digits=12, decimal_places=2)
    hours_per_day = models.DecimalField(max_digits=4, decimal_places=2, default=8)
    # An hour of overtime is paid at the hourly rate × this.
    overtime_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=1.5)
    # An absent day costs its pay × this (1 = just the day's pay).
    absence_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    # Working on a public holiday or approved leave pays the day × this.
    holiday_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    insured_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    annual_leave_days = models.PositiveSmallIntegerField(default=21)
    permission_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # a month

    class Meta(EffectiveDatedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "employee", "effective_from"],
                                    name="employees_compensation_from_uniq"),
            models.CheckConstraint(
                condition=Q(salary__gte=0, hours_per_day__gt=0, hours_per_day__lte=24,
                            overtime_multiplier__gte=0, absence_multiplier__gte=0,
                            holiday_multiplier__gte=0, permission_hours__gte=0),
                name="employees_compensation_values_check"),
        ]

    @property
    def terms(self):
        from .domain.rates import PayTerms

        return PayTerms.of(self)


class Weekday(models.IntegerChoices):  # Python's date.weekday()
    MONDAY = 0, _("Monday")
    TUESDAY = 1, _("Tuesday")
    WEDNESDAY = 2, _("Wednesday")
    THURSDAY = 3, _("Thursday")
    FRIDAY = 4, _("Friday")
    SATURDAY = 5, _("Saturday")
    SUNDAY = 6, _("Sunday")


class WorkSchedule(EffectiveDatedModel):
    """When the employee works from `effective_from` on (PayRole: `Pfe1.fhour`, `thour`,
    `day_off`, `addt`, `over`, `early`; shift changes there overwrote the card).

    A shift may end after midnight (`ends_at` < `starts_at`): it belongs to the day it starts.
    No lateness policy: missing time is deducted as it is. No overtime policy: no overtime."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="schedules")
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    days_off = ArrayField(models.PositiveSmallIntegerField(choices=Weekday.choices),
                          default=list, blank=True)
    lateness_policy = models.ForeignKey("policies.LatenessPolicy", null=True, blank=True,
                                        on_delete=models.PROTECT, related_name="+")
    overtime_policy = models.ForeignKey("policies.OvertimePolicy", null=True, blank=True,
                                        on_delete=models.PROTECT, related_name="+")
    # Leaving up to this many minutes early is not deducted.
    early_leave_minutes = models.PositiveSmallIntegerField(default=0)

    class Meta(EffectiveDatedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "employee", "effective_from"],
                                    name="employees_schedule_from_uniq"),
        ]
