"""Money paid to employees ahead and recovered from their pay.

* `Advance` (PayRole: `Pfe2` with `code2=1`, "دفعة من مرتب"): part of a month's salary paid
  early, recovered whole by the payroll of the month it falls in.
* `Loan` (PayRole: `Pfe2` with `code3=1`) and its `LoanInstallment` rows (`Pfe2_i`): a sum
  recovered in monthly installments.

PayRole kept both, and allowances, in one table told apart by which columns were filled; here
each is its own table. Payroll (phase 4) marks advances recovered and installments paid when a
payroll is posted; PayRole did it while calculating.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class AdvanceStatus(models.TextChoices):
    OPEN = "open", _("To be recovered")
    RECOVERED = "recovered", _("Recovered")
    CANCELLED = "cancelled", _("Cancelled")


class Advance(TenantScopedModel):
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="advances")
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=AdvanceStatus.choices,
                              default=AdvanceStatus.OPEN)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["tenant", "employee", "date"],
                                name="loans_advance_emp_idx")]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0),
                                              name="loans_advance_amount_check")]

    def __str__(self):
        return f"{self.employee_id} {self.date} {self.amount}"


class LoanStatus(models.TextChoices):
    ACTIVE = "active", _("Being repaid")
    SETTLED = "settled", _("Repaid")
    CANCELLED = "cancelled", _("Cancelled")


class Loan(TenantScopedModel):
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="loans")
    granted_on = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=LoanStatus.choices,
                              default=LoanStatus.ACTIVE)

    class Meta:
        ordering = ["-granted_on", "-id"]
        indexes = [models.Index(fields=["tenant", "employee"], name="loans_loan_emp_idx")]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0),
                                              name="loans_loan_amount_check")]

    def __str__(self):
        return f"{self.employee_id} {self.granted_on} {self.amount}"


class InstallmentStatus(models.TextChoices):
    DUE = "due", _("Due")
    PAID = "paid", _("Paid")
    CANCELLED = "cancelled", _("Cancelled")


class LoanInstallment(TenantScopedModel):
    """One month's share of a loan, deducted by the payroll of `due_month` (its first day)."""

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveSmallIntegerField()
    due_month = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=InstallmentStatus.choices,
                              default=InstallmentStatus.DUE)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "loan", "number"],
                                    name="loans_installment_number_uniq"),
            models.CheckConstraint(condition=Q(amount__gt=0, due_month__day=1),
                                   name="loans_installment_values_check"),
        ]

    def __str__(self):
        return f"{self.loan_id} #{self.number} {self.due_month:%Y-%m}"
