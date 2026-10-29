"""Incentives and penalties given to employees on a day, added to or deducted from that month's
pay.

PayRole kept both in one table (`Pun.Pfe5a`, `k` 1 or 2) with their two type catalogues in two
apps (`Inc.Pa1`, `Pun.Pa2`). Here one `AdjustmentType` catalogue has a kind, and each
`Adjustment` keeps the amount worked out when it was given (apps.adjustments.domain.amounts), so
a later raise doesn't change last month's penalty. Entries given together (a department, a
branch) share a `batch`.
"""

from __future__ import annotations

import uuid

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


class AdjustmentStatus(models.TextChoices):
    ACTIVE = "active", _("In effect")
    CANCELLED = "cancelled", _("Cancelled")


class Adjustment(TenantScopedModel):
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
    batch = models.UUIDField(default=uuid.uuid4)
    status = models.CharField(max_length=10, choices=AdjustmentStatus.choices,
                              default=AdjustmentStatus.ACTIVE)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["tenant", "employee", "date"],
                                name="adjustments_emp_date_idx"),
                   models.Index(fields=["tenant", "batch"], name="adjustments_batch_idx")]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0, amount__gte=0),
                                              name="adjustments_values_check")]

    def __str__(self):
        return f"{self.employee_id} {self.kind} {self.date} {self.amount}"
