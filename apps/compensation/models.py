"""Pay items: the catalogue of allowances and other additions and deductions, and the entries
giving an item to employees on a schedule (`PayItemAssignment`), summed by payroll.

PayRole kept two catalogues in one table (`Allow.Pfn1`: `code` for allowances, `code1` for other
items). Here an item is one row with a kind; its daily/monthly basis is applied as labelled
(PayRole multiplied the "monthly" ones by days worked: Salary/payroll.py:321).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class PayItemKind(models.TextChoices):
    ADDITION = "addition", _("Addition")
    DEDUCTION = "deduction", _("Deduction")


class PayItemBasis(models.TextChoices):
    FIXED = "fixed", _("Fixed amount for the month")
    PER_DAY = "per_day", _("Amount per day worked")


class PayItem(TenantScopedModel):
    code = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=PayItemKind.choices)
    basis = models.CharField(max_length=8, choices=PayItemBasis.choices,
                             default=PayItemBasis.FIXED)
    taxable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="compensation_item_code_uniq"),
            models.UniqueConstraint(fields=["tenant", "name"], name="compensation_item_name_uniq"),
        ]

    def __str__(self):
        return self.name


class AssignmentStatus(models.TextChoices):
    ACTIVE = "active", _("In effect")
    CANCELLED = "cancelled", _("Cancelled")


class ItemFrequency(models.TextChoices):
    ONCE = "once", _("Once")
    PERIOD = "period", _("Every pay period")
    MONTHLY = "monthly", _("Every month")
    WEEKLY = "weekly", _("Every week")


class PayItemAssignment(TenantScopedModel):
    """An item given to one employee on a schedule (PayRole: `Pfe2` with `so1`/`so2`, one row per
    month): once on `starts_on`, or every pay period, month or week from `starts_on` to `ends_on`
    (open when empty). Payroll allocates it to its periods (docs/payroll-design.md §4), prorated
    when the employee or the item covers only part of a period.

    The amount is for one unit of the frequency, or, for a per-day item, for each day worked. The
    same item can't run twice over the same days for an employee. Assignments made together share
    a `batch`."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="pay_item_assignments")
    item = models.ForeignKey(PayItem, on_delete=models.PROTECT, related_name="assignments")
    frequency = models.CharField(max_length=8, choices=ItemFrequency.choices,
                                 default=ItemFrequency.MONTHLY)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    batch = models.UUIDField(default=uuid.uuid4)
    status = models.CharField(max_length=10, choices=AssignmentStatus.choices,
                              default=AssignmentStatus.ACTIVE)

    class Meta:
        ordering = ["-starts_on", "employee_id"]
        indexes = [
            models.Index(fields=["tenant", "employee", "starts_on"],
                         name="compensation_assign_emp_idx"),
            models.Index(fields=["tenant", "batch"], name="compensation_entry_batch_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0)
                & (Q(ends_on__isnull=True) | Q(ends_on__gte=models.F("starts_on")))
                & (~Q(frequency="once") | Q(ends_on=models.F("starts_on"))),
                name="compensation_assignment_values_check"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.item_id} {self.frequency} {self.starts_on}"
