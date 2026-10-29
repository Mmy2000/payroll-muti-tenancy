"""Pay items: the catalogue of allowances and other additions and deductions, and the entries
giving an item to employees for a month (`PayItemEntry`), summed by payroll.

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


class EntryStatus(models.TextChoices):
    ACTIVE = "active", _("In effect")
    CANCELLED = "cancelled", _("Cancelled")


class PayItemEntry(TenantScopedModel):
    """An item given to one employee for one month (PayRole: `Pfe2` with `so1`/`so2`). The
    amount is for the month (a fixed item) or for each day worked (a per-day item). An item is
    given once a month per employee. Entries made together share a `batch`."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="pay_item_entries")
    item = models.ForeignKey(PayItem, on_delete=models.PROTECT, related_name="entries")
    month = models.DateField()  # its first day
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=300, blank=True)
    batch = models.UUIDField(default=uuid.uuid4)
    status = models.CharField(max_length=10, choices=EntryStatus.choices,
                              default=EntryStatus.ACTIVE)

    class Meta:
        ordering = ["-month", "employee_id"]
        indexes = [models.Index(fields=["tenant", "month"], name="compensation_entry_month_idx"),
                   models.Index(fields=["tenant", "batch"], name="compensation_entry_batch_idx")]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "employee", "item", "month"],
                                    condition=Q(status="active"),
                                    name="compensation_entry_once_a_month_uniq"),
            models.CheckConstraint(condition=Q(amount__gt=0, month__day=1),
                                   name="compensation_entry_values_check"),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.item_id} {self.month}"
