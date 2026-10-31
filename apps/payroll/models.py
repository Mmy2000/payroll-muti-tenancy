"""Payroll: calendars, periods, runs and payslips (docs/payroll-design.md §2–§6).

PayRole kept one row per employee and run (`Salary.Pfe6`, ~90 columns, money as integers) and
recalculated paid runs from today's cards. Here a payslip is lines (code, quantity, rate, amount)
plus a frozen snapshot of what it was calculated from, and an approved run records what it paid
(`PaidSource`), so nothing can be paid twice.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class Frequency(models.TextChoices):
    MONTHLY = "monthly", _("Monthly")
    BIWEEKLY = "biweekly", _("Every two weeks")
    WEEKLY = "weekly", _("Weekly")


class MonthlyRule(models.TextChoices):
    SPLIT = "split", _("Shared between the weeks by days")
    FIRST_RUN = "first_run", _("Whole in the week containing the 1st")


class PayCalendar(TenantScopedModel):
    """How a pay frequency's periods fall. Monthly: from `start_day` (1 = calendar months).
    Weekly and biweekly: periods of 7 or 14 days counted from `anchor`."""

    frequency = models.CharField(max_length=8, choices=Frequency.choices)
    start_day = models.PositiveSmallIntegerField(default=1)
    anchor = models.DateField(null=True, blank=True)
    monthly_items = models.CharField(max_length=10, choices=MonthlyRule.choices,
                                     default=MonthlyRule.SPLIT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "frequency"],
                                    name="payroll_calendar_frequency_uniq"),
            models.CheckConstraint(condition=Q(start_day__gte=1, start_day__lte=28),
                                   name="payroll_calendar_start_day_check"),
            models.CheckConstraint(condition=Q(frequency="monthly") | Q(anchor__isnull=False),
                                   name="payroll_calendar_anchor_check"),
        ]

    def __str__(self):
        return self.frequency


class PeriodKind(models.TextChoices):
    REGULAR = "regular", _("Regular")
    OFF_CYCLE = "off_cycle", _("Off-cycle")


class PeriodStatus(models.TextChoices):
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class PayrollPeriod(TenantScopedModel):
    frequency = models.CharField(max_length=8, choices=Frequency.choices)
    kind = models.CharField(max_length=10, choices=PeriodKind.choices,
                            default=PeriodKind.REGULAR)
    start = models.DateField()
    end = models.DateField()
    status = models.CharField(max_length=8, choices=PeriodStatus.choices,
                              default=PeriodStatus.OPEN)
    reason = models.CharField(max_length=300, blank=True)  # off-cycle: why

    class Meta:
        ordering = ["-start", "frequency"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "frequency", "start", "end"],
                                    condition=Q(kind="regular"),
                                    name="payroll_period_regular_uniq"),
            models.CheckConstraint(condition=Q(end__gte=models.F("start")),
                                   name="payroll_period_range_check"),
        ]

    def __str__(self):
        return f"{self.frequency} {self.start}–{self.end}"


class RunStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    APPROVED = "approved", _("Approved")
    PAID = "paid", _("Paid")
    REVERSED = "reversed", _("Reversed")


LIVE = (RunStatus.DRAFT, RunStatus.APPROVED, RunStatus.PAID)
FINAL = (RunStatus.APPROVED, RunStatus.PAID)


class ScopeKind(models.TextChoices):
    ALL = "all", _("Everyone")
    BRANCH = "branch", _("A branch")
    DEPARTMENT = "department", _("A department")


class PayrollRun(TenantScopedModel):
    @property
    def branch_in_scope(self) -> int | None:
        """The one branch this run is limited to, if it is."""
        return self.scope_id if self.scope == ScopeKind.BRANCH else self.scope_branch_id

    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name="runs")
    scope = models.CharField(max_length=10, choices=ScopeKind.choices, default=ScopeKind.ALL)
    scope_id = models.PositiveBigIntegerField(null=True, blank=True)  # the branch or department
    # A department run for one branch (a department spans several); empty for all of it.
    scope_branch_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=RunStatus.choices, default=RunStatus.DRAFT)
    number = models.CharField(max_length=32, null=True, blank=True)  # noqa: DJ001 (on approval)
    note = models.CharField(max_length=300, blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    # Employees of the scope left out, with why: [{"employee_id", "name", "reason"}].
    skipped = models.JSONField(default=list, blank=True)
    earnings = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    employer_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    paid_on = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=40, blank=True)
    payment_reference = models.CharField(max_length=120, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.PROTECT, related_name="+")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    reversal_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-period__start", "-id"]
        indexes = [models.Index(fields=["tenant", "period"], name="payroll_run_period_idx")]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], condition=Q(number__isnull=False),
                                    name="payroll_run_number_uniq"),
        ]

    def __str__(self):
        return self.number or f"#{self.pk}"

    @property
    def is_draft(self) -> bool:
        return self.status == RunStatus.DRAFT


class Payslip(TenantScopedModel):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="payslips")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="payslips")
    # Where the employee was at the end of the period: reports stay right after a transfer.
    branch = models.ForeignKey("org.Branch", null=True, on_delete=models.PROTECT,
                               related_name="+")
    department = models.ForeignKey("org.Department", null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="+")
    earnings = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    employer_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    blocking = models.PositiveSmallIntegerField(default=0)
    warnings = models.PositiveSmallIntegerField(default=0)
    issues = models.JSONField(default=list, blank=True)  # [{"severity", "code", "params"}]
    snapshot = models.JSONField(default=dict, blank=True)  # the inputs (domain.inputs)

    class Meta:
        ordering = ["employee__code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "run", "employee"],
                                    name="payroll_payslip_employee_uniq"),
        ]
        indexes = [models.Index(fields=["tenant", "employee"], name="payroll_payslip_emp_idx")]

    def __str__(self):
        return f"{self.run_id}/{self.employee_id}"


class LineKind(models.TextChoices):
    EARNING = "earning", _("Earning")
    DEDUCTION = "deduction", _("Deduction")
    EMPLOYER = "employer", _("Employer cost")


class PayslipLine(TenantScopedModel):
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField()
    code = models.CharField(max_length=30)
    kind = models.CharField(max_length=10, choices=LineKind.choices)
    label = models.CharField(max_length=200, blank=True)  # a name; system lines use their code
    quantity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    taxable = models.BooleanField(default=False)
    source = models.CharField(max_length=60, blank=True)  # "app.Model"
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    slice = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["position"]
        indexes = [models.Index(fields=["tenant", "payslip"], name="payroll_line_payslip_idx")]


class ManualLine(TenantScopedModel):
    """A line a manager adds to an employee's payslip in a draft run (a correction, a one-off
    payment). Kept across recalculations; frozen with the run when it is approved."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="manual_lines")
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="+")
    label = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    addition = models.BooleanField(default=True)
    taxable = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["tenant", "run", "employee"],
                                name="payroll_manual_run_emp_idx")]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0),
                                              name="payroll_manual_amount_check")]


class PaidSource(TenantScopedModel):
    """Something an approved payslip paid: an installment, an advance, an incentive, a share of
    a pay item… At most one live record per source and share (`slice`), so nothing is paid
    twice; a reversal releases them."""

    payslip = models.ForeignKey(Payslip, on_delete=models.PROTECT, related_name="paid_sources")
    source = models.CharField(max_length=60)
    source_id = models.PositiveBigIntegerField()
    slice = models.CharField(max_length=30, blank=True)
    released = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "source", "source_id", "slice"],
                                    condition=Q(released=False),
                                    name="payroll_paid_once_uniq"),
        ]
        indexes = [models.Index(fields=["tenant", "payslip"], name="payroll_paid_payslip_idx")]
