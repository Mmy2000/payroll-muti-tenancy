"""Incentives and penalties given to employees on a day, added to or deducted from that period's
pay.

PayRole kept both in one table (`Pun.Pfe5a`, `k` 1 or 2) with their two type catalogues in two
apps (`Inc.Pa1`, `Pun.Pa2`), and edited a batch in place (`edit_batch`). Here one
`AdjustmentType` catalogue has a kind; what is given together is an `AdjustmentBatch` (one
employee, a department or a branch) with one `Adjustment` row per employee, each keeping the
amount worked out when it was given (apps.adjustments.domain.amounts), so a later raise doesn't
change last month's penalty.

A batch is a **draft** (edited freely, never paid) until it is **approved** (paid by the next
payroll). An approved batch is changed only on purpose, with a reason: reopened to a draft, or
cancelled, while no approved payroll has paid it; once one has, it is never overwritten, a
**correction** batch (`corrects`) pays or takes back the difference in a later payroll.
`change_reason` and `revision` record why each change was made; the audit trail records who,
when and what.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel

from .domain.amounts import CHOICES


class AdjustmentKind(models.TextChoices):
    INCENTIVE = "incentive", _("Incentive")
    PENALTY = "penalty", _("Penalty")


class AdjustmentType(TenantScopedModel):
    code = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=AdjustmentKind.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "kind", "code"],
                                    name="adjustments_type_code_uniq"),
            models.UniqueConstraint(fields=["tenant", "kind", "name"],
                                    name="adjustments_type_name_uniq"),
        ]

    def __str__(self):
        return self.name


class BatchStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    APPROVED = "approved", _("Approved")
    CANCELLED = "cancelled", _("Cancelled")


class AdjustmentBatch(TenantScopedModel):
    kind = models.CharField(max_length=10, choices=AdjustmentKind.choices)
    adjustment_type = models.ForeignKey(AdjustmentType, on_delete=models.PROTECT,
                                        related_name="+")
    date = models.DateField()
    method = models.CharField(max_length=8, choices=CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300, blank=True)
    # Who it was given to (apps.employees.selectors); empty for a correction.
    target_kind = models.CharField(max_length=10, blank=True)
    target_id = models.BigIntegerField(null=True, blank=True)
    # A department given to in one branch (a department spans several); empty for all of it.
    target_branch_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=BatchStatus.choices,
                              default=BatchStatus.DRAFT)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    corrects = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="corrections")
    revision = models.PositiveIntegerField(default=1)
    change_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["tenant", "kind", "status", "date"],
                                name="adjustments_batch_list_idx")]
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=0),
                                              name="adjustments_batch_quantity_check")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.date} #{self.pk}"


class Adjustment(TenantScopedModel):
    """One employee's row of a batch. A correction row's `amount` is the signed difference it
    pays (more) or takes back (less) against the row it `corrects`."""

    batch = models.ForeignKey(AdjustmentBatch, on_delete=models.CASCADE, related_name="rows")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="adjustments")
    adjustment_type = models.ForeignKey(AdjustmentType, on_delete=models.PROTECT,
                                        related_name="+")
    kind = models.CharField(max_length=10, choices=AdjustmentKind.choices)  # the type's
    date = models.DateField()
    method = models.CharField(max_length=8, choices=CHOICES)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300, blank=True)
    corrects = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="corrections")

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["tenant", "employee", "date"],
                                name="adjustments_emp_date_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(corrects__isnull=True, quantity__gt=0, amount__gte=0)
                | Q(corrects__isnull=False, quantity__gte=0),
                name="adjustments_values_check"),
            models.UniqueConstraint(fields=["tenant", "batch", "employee"],
                                    name="adjustments_batch_employee_uniq"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.kind} {self.date} {self.amount}"
