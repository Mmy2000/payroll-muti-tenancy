"""The rules payroll applies, set up once per client: lateness and overtime policies (with
their bands), income tax tables, social insurance rates and public holidays.

PayRole kept bands as numbered columns on the group (`Pfn.fr1..5`, `ofr1..5`) and tax brackets
as `Ptax.fr1..7`; here they are rows. Rates are always percentages (14 = 14 %), never the
"under 1 means a fraction" guess PayRole made.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import EffectiveDatedModel, TenantScopedModel


class LatenessPolicy(TenantScopedModel):
    """How arriving late is deducted. Minutes late fall in a band, and the band says how many
    hours of pay are deducted. Lateness inside `grace_minutes` is ignored. An employee whose
    schedule has no policy loses exactly the time they missed instead."""

    name = models.CharField(max_length=120)
    grace_minutes = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "name"],
                                               name="policies_lateness_name_uniq")]

    def __str__(self):
        return self.name


class LatenessBand(TenantScopedModel):
    policy = models.ForeignKey(LatenessPolicy, on_delete=models.CASCADE, related_name="bands")
    from_minutes = models.PositiveSmallIntegerField()
    to_minutes = models.PositiveSmallIntegerField()
    deduct_hours = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ["from_minutes"]
        indexes = [models.Index(fields=["tenant", "policy"], name="policies_lateband_policy_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(to_minutes__gte=models.F("from_minutes"),
                                               deduct_hours__gte=0),
                                   name="policies_lateband_values_check"),
        ]


class OvertimePolicy(TenantScopedModel):
    """How extra time is paid. Overtime counts only after `starts_after_minutes` past the end of
    the shift (PayRole's "overtime starts after", which it stored but never applied). With bands,
    the minutes worked over fall in a band that says how many hours are paid; without bands the
    hours actually worked over are paid. The employee's overtime multiplier applies on top."""

    name = models.CharField(max_length=120)
    starts_after_minutes = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "name"],
                                               name="policies_overtime_name_uniq")]

    def __str__(self):
        return self.name


class OvertimeBand(TenantScopedModel):
    policy = models.ForeignKey(OvertimePolicy, on_delete=models.CASCADE, related_name="bands")
    from_minutes = models.PositiveSmallIntegerField()
    to_minutes = models.PositiveSmallIntegerField()
    paid_hours = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ["from_minutes"]
        indexes = [models.Index(fields=["tenant", "policy"], name="policies_otband_policy_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(to_minutes__gte=models.F("from_minutes"),
                                               paid_hours__gte=0),
                                   name="policies_otband_values_check"),
        ]


class TaxTable(EffectiveDatedModel):
    """Income tax from `effective_from` on, for the whole client: yearly taxable income less
    `annual_exemption`, taxed bracket by bracket (PayRole: `Enp.Ptax`)."""

    annual_exemption = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta(EffectiveDatedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "effective_from"],
                                    name="policies_taxtable_from_uniq"),
            models.CheckConstraint(condition=Q(annual_exemption__gte=0),
                                   name="policies_taxtable_exemption_check"),
        ]

    def __str__(self):
        return f"{self.effective_from}"


class TaxBracket(TenantScopedModel):
    """Yearly income up to `up_to` (after the brackets below it) is taxed at `rate` percent.
    The last bracket has no `up_to`: everything above."""

    table = models.ForeignKey(TaxTable, on_delete=models.CASCADE, related_name="brackets")
    up_to = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=6, decimal_places=3)

    class Meta:
        ordering = [models.F("up_to").asc(nulls_last=True)]
        indexes = [models.Index(fields=["tenant", "table"], name="policies_taxbracket_table_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(rate__gte=0, rate__lte=100),
                                   name="policies_taxbracket_rate_check"),
        ]


class InsuranceRate(EffectiveDatedModel):
    """Social insurance from `effective_from` on (PayRole: `Enp.Pins`): percentages of the
    insured salary paid by the employee (deducted from pay) and by the employer. The insured
    salary is kept within `min_insured`..`max_insured` when they are set."""

    employee_rate = models.DecimalField(max_digits=6, decimal_places=3)
    employer_rate = models.DecimalField(max_digits=6, decimal_places=3)
    min_insured = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_insured = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta(EffectiveDatedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "effective_from"],
                                    name="policies_insurance_from_uniq"),
            models.CheckConstraint(condition=Q(employee_rate__gte=0, employee_rate__lte=100,
                                               employer_rate__gte=0, employer_rate__lte=100),
                                   name="policies_insurance_rates_check"),
        ]

    def __str__(self):
        return f"{self.effective_from}"


class PublicHoliday(TenantScopedModel):
    """A paid day off. No branch = every branch (PayRole: `Enp.Pvac`)."""

    date = models.DateField()
    name = models.CharField(max_length=120)
    branch = models.ForeignKey("org.Branch", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")

    class Meta:
        ordering = ["-date"]
        verbose_name = _("public holiday")
        constraints = [
            models.UniqueConstraint(fields=["tenant", "date", "branch"], nulls_distinct=False,
                                    name="policies_holiday_day_uniq"),
        ]

    def __str__(self):
        return f"{self.date} {self.name}"
