"""Reading one employee's payslip inputs for a period (apps.payroll.domain.inputs) from the
database. The only part of payroll that knows the other apps' tables; the engine reads only
what this returns.

What another approved payslip already paid (`PaidSource`) is left out, so it can't be paid
twice; what is still due is allocated to the period by apps.payroll.domain.allocation.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.adjustments.models import Adjustment, BatchStatus
from apps.attendance.selectors import evaluate
from apps.compensation.models import AssignmentStatus, ItemFrequency, PayItemAssignment
from apps.core.history import Timeline, in_effect
from apps.employees.domain.rates import PERIODS_A_YEAR
from apps.loans.models import Advance, AdvanceStatus, InstallmentStatus, LoanInstallment
from apps.platform.tenants import features
from apps.policies.domain.bands import Band
from apps.policies.domain.tax import Bracket
from apps.policies.models import InsuranceRate, TaxTable

from .domain import allocation
from .domain.inputs import (
    OFF_CYCLE,
    REGULAR,
    Amount,
    Insurance,
    Lateness,
    ManualLine,
    Overtime,
    PayDay,
    PayslipInput,
    Tax,
)
from .domain.periods import Period
from .models import PaidSource


def _employed(employee, period: Period) -> Period | None:
    start = max(employee.hired_on, period.start)
    end = period.end if employee.left_on is None else min(employee.left_on, period.end)
    return Period(start, end) if start <= end else None


def _days_between(span: Period):
    day = span.start
    while day <= span.end:
        yield day
        day += timedelta(days=1)


def _bands(policy, hours_field: str) -> tuple[Band, ...]:
    return tuple(Band(b.from_minutes, b.to_minutes, getattr(b, hours_field))
                 for b in policy.bands.all())


class _Policies:
    """Lateness and overtime policies, read once per run."""

    def __init__(self):
        self._cache: dict = {}

    def lateness(self, policy):
        if policy is None:
            return None
        key = ("late", policy.pk)
        if key not in self._cache:
            self._cache[key] = Lateness(policy.grace_minutes, _bands(policy, "deduct_hours"))
        return self._cache[key]

    def overtime(self, policy):
        if policy is None:
            return None
        key = ("over", policy.pk)
        if key not in self._cache:
            self._cache[key] = Overtime(policy.starts_after_minutes,
                                        _bands(policy, "paid_hours"))
        return self._cache[key]


def _paid(source: str, ids, slice_: str = "") -> set[int]:
    """The ids of `source` an approved payslip already paid (for this slice)."""
    return set(PaidSource.objects.filter(source=source, source_id__in=list(ids), slice=slice_,
                                         released=False).values_list("source_id", flat=True))


class Gatherer:
    """Gathers payslip inputs for one run: what is the same for every employee is read once."""

    def __init__(self, period: Period, kind: str, frequency: str, calendar, tenant_id: int):
        self.period, self.kind, self.frequency = period, kind, frequency
        self.monthly_rule = calendar.monthly_items if calendar else allocation.SPLIT
        self.features = features.enabled_keys(tenant_id) | {"payroll"}
        self.today = timezone.localdate()
        self.policies = _Policies()
        self.insurance = in_effect(InsuranceRate.objects.all(), period.end)
        self.tax_table = in_effect(TaxTable.objects.prefetch_related("brackets"), period.end)

    # --- days ------------------------------------------------------------------------------

    def _days(self, employee, employed: Period, pay: Timeline, schedules: Timeline,
              attendance: bool) -> tuple[PayDay, ...]:
        results = ({r.day: r for r in evaluate([employee], employed.start, employed.end,
                                               today=self.today)[employee.pk]}
                   if attendance else {})
        days = []
        for day in _days_between(employed):
            terms_row = pay.on(day)
            if terms_row is None:
                continue
            schedule = schedules.on(day)
            result = results.get(day)
            common = {
                "terms": terms_row.terms, "overtime_multiplier": terms_row.overtime_multiplier,
                "absence_multiplier": terms_row.absence_multiplier,
                "holiday_multiplier": terms_row.holiday_multiplier,
                "early_leave_minutes": schedule.early_leave_minutes if schedule else 0,
                "lateness": self.policies.lateness(schedule.lateness_policy if schedule else None),
                "overtime": self.policies.overtime(schedule.overtime_policy if schedule else None),
            }
            if result is None:
                days.append(PayDay(day=day, status="unknown", **common))
                continue
            days.append(PayDay(
                day=day, status=str(result.status), rest_day=result.rest_day,
                marked_day_off=result.marked_day_off,
                holiday=bool(result.holiday),
                leave=bool(result.leave), paid=result.paid,
                worked_minutes=result.worked_minutes, late_minutes=result.late_minutes,
                early_minutes=result.early_minutes, missing_check_out=result.missing_check_out,
                hourly_minutes=result.hourly_minutes, **common))
        return tuple(days)

    # --- amounts ---------------------------------------------------------------------------

    def _items(self, employee, employed: Period) -> list[Amount]:
        rows = (PayItemAssignment.objects.filter(employee=employee,
                                                 status=AssignmentStatus.ACTIVE,
                                                 starts_on__lte=employed.end)
                .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=employed.start))
                .select_related("item"))
        if self.kind == OFF_CYCLE:
            rows = rows.filter(frequency=ItemFrequency.ONCE)
        window_of = allocation.Window
        slice_ = f"{self.period.start}..{self.period.end}"
        rows = list(rows)
        paid_once = _paid("compensation.PayItemAssignment",
                          [r.pk for r in rows if r.frequency == ItemFrequency.ONCE])
        paid_recurring = _paid("compensation.PayItemAssignment",
                               [r.pk for r in rows if r.frequency != ItemFrequency.ONCE], slice_)
        amounts = []
        for row in rows:
            window = window_of(max(row.starts_on, employed.start),
                               employed.end if row.ends_on is None
                               else min(row.ends_on, employed.end))
            per_day = row.item.basis == "per_day"
            if row.frequency == ItemFrequency.ONCE:
                if row.pk in paid_once:
                    continue
                amount = allocation.once(row.amount, row.starts_on, self.period, window)
                share = ""
            else:
                if row.pk in paid_recurring:
                    continue
                amount = (row.amount if per_day else
                          allocation.rule_for(row.frequency, self.frequency, self.monthly_rule)(
                              row.amount, self.period, window))
                share = slice_
            if not amount:
                continue
            amounts.append(Amount(
                code="item", label=row.item.name, amount=amount,
                addition=row.item.kind == "addition", taxable=row.item.taxable,
                source="compensation.PayItemAssignment", source_id=row.pk, slice=share,
                per_day=per_day, start=window.start, end=window.end))
        return amounts

    def _dated(self, employee, span: Period) -> list[Amount]:
        amounts = []
        adjustments = list(Adjustment.objects.filter(
            employee=employee, batch__status=BatchStatus.APPROVED,
            date__range=(span.start, span.end)).select_related("adjustment_type", "corrects"))
        paid = _paid("adjustments.Adjustment", [a.pk for a in adjustments])
        for row in adjustments:
            if row.pk in paid or not row.amount:
                continue
            # A correction that takes back turns the line around: a penalty given back is
            # added to pay, an incentive taken back is deducted (and lowers the taxable pay).
            incentive = row.kind == "incentive"
            label = row.adjustment_type.name
            if row.corrects_id:
                label = _("%(name)s, correction of %(day)s") % {
                    "name": label, "day": row.corrects.date.isoformat()}
            amounts.append(Amount(
                code=row.kind, label=label, amount=abs(row.amount),
                addition=incentive == (row.amount > 0), taxable=incentive,
                source="adjustments.Adjustment", source_id=row.pk))
        advances = list(Advance.objects.filter(employee=employee, status=AdvanceStatus.OPEN,
                                               date__range=(span.start, span.end)))
        paid = _paid("loans.Advance", [a.pk for a in advances])
        for row in advances:
            if row.pk not in paid:
                amounts.append(Amount(code="advance", label="", amount=row.amount,
                                      addition=False, taxable=False, source="loans.Advance",
                                      source_id=row.pk))
        return amounts

    def _installments(self, employee) -> list[Amount]:
        """Due installments whose due date (the 1st of their month) is in the period, whole."""
        rows = list(LoanInstallment.objects.filter(
            loan__employee=employee, status=InstallmentStatus.DUE,
            due_month__range=(self.period.start, self.period.end)))
        paid = _paid("loans.LoanInstallment", [r.pk for r in rows])
        return [Amount(code="installment", label=f"#{row.number}", amount=row.amount,
                       addition=False, taxable=False, source="loans.LoanInstallment",
                       source_id=row.pk) for row in rows if row.pk not in paid]

    # --- insurance and tax -----------------------------------------------------------------

    def _insurance(self, insured_salary: Decimal) -> Insurance | None:
        rates = self.insurance
        if rates is None:
            return None
        insured = insured_salary
        if rates.min_insured is not None:
            insured = max(insured, rates.min_insured)
        if rates.max_insured is not None:
            insured = min(insured, rates.max_insured)
        # Insurance is monthly: a weekly or biweekly period gets its share by days.
        share = allocation.rule_for("monthly", self.frequency, allocation.SPLIT)(
            insured, self.period, allocation.Window(self.period.start, self.period.end))
        return Insurance(share, rates.employee_rate, rates.employer_rate, rates.pk)

    def _tax(self) -> Tax | None:
        table = self.tax_table
        if table is None:
            return None
        return Tax(table.annual_exemption,
                   tuple(Bracket(b.up_to, b.rate) for b in table.brackets.all()),
                   PERIODS_A_YEAR[self.frequency], table.pk)

    # --- the payslip -----------------------------------------------------------------------

    def payslip_input(self, employee, manual=()) -> PayslipInput:
        employed = _employed(employee, self.period)
        pay = Timeline(employee.pay_history.all())
        last_day = employed.end if employed else self.period.end
        current = pay.on(last_day)
        attendance = self.kind == REGULAR and "attendance" in self.features
        base = {"employee_id": employee.pk, "employee_name": employee.name, "kind": self.kind,
                "period": self.period, "pay_frequency": self.frequency, "employed": employed,
                "terms": current.terms if current else None, "features": self.features,
                "today": self.today,
                "manual": tuple(ManualLine(m.label, m.amount, m.addition, m.taxable, m.pk)
                                for m in manual)}
        if employed is None:
            return PayslipInput(**base)
        span = employed if self.kind == REGULAR else self.period
        amounts = self._dated(employee, span)
        if self.kind == REGULAR:
            amounts += self._items(employee, employed) + self._installments(employee)
            days = self._days(employee, employed, pay,
                              Timeline(employee.schedules.select_related(
                                  "lateness_policy", "overtime_policy")
                                  .prefetch_related("lateness_policy__bands",
                                                    "overtime_policy__bands")),
                              attendance)
        else:
            amounts += self._items(employee, employed)
            days = ()
        insured = bool(current and current.insured_salary)
        return PayslipInput(
            **base, days=days, attendance=attendance, amounts=tuple(amounts), insured=insured,
            insurance=self._insurance(current.insured_salary) if insured else None,
            tax=self._tax())
