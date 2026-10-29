"""The payroll engine: one payslip from its inputs (docs/payroll-design.md §5). Pure: no database.

A pipeline of calculators, run in order. Each owns one part of the payslip, says which feature
it belongs to (skipped when the feature is off for the client) and which kinds of run it applies
to (regular, off-cycle). Adding a part of pay means adding a calculator to `CALCULATORS`.

PayRole's calculation (Salary/payroll.py `run_employee`) is followed rule by rule; where this
differs, docs/payroll-design.md says so. Lines and issues carry codes, not texts, so a payslip
reads in the viewer's language (`LINE_LABELS`, `ISSUES`).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.core.numeric import ZERO, round_money
from apps.employees.domain.rates import DAILY, FIXED, HOURLY, PERIOD_DAYS
from apps.policies.domain.bands import band_for
from apps.policies.domain.tax import yearly_tax

from .inputs import OFF_CYCLE, REGULAR, PayDay, PayslipInput

EARNING, DEDUCTION, EMPLOYER = "earning", "deduction", "employer"
BLOCKING, WARNING = "blocking", "warning"
SIXTY, HUNDRED = Decimal(60), Decimal(100)
PAID_AWAY = {"day_off", "holiday"}  # days not worked that are paid anyway
UNPAID_AWAY = {"absent", "excused"}

LINE_LABELS = {
    "salary": _("Salary"),
    "day_wage": _("Days paid × day's wage"),
    "hour_wage": _("Hours paid × hour's wage"),
    "days_not_paid": _("Days not paid"),
    "absence_penalty": _("Absence penalty"),
    "holiday_work": _("Work on holidays and leave days"),
    "overtime": _("Overtime"),
    "missing_time": _("Missing time"),
    "lateness": _("Lateness"),
    "incentive": _("Incentive"),
    "penalty": _("Penalty"),
    "advance": _("Salary advance"),
    "installment": _("Loan installment"),
    "insurance_employee": _("Social insurance (employee share)"),
    "insurance_employer": _("Social insurance (employer share)"),
    "income_tax": _("Income tax"),
}
ISSUES = {
    "no_pay": _("No pay is recorded for this period."),
    "needs_attendance": _("A daily or hourly wage is counted from attendance, which is off."),
    "insurance_missing": _("Insured, but no insurance rates are set for this period."),
    "no_tax_table": _("No income tax table applies to this period: no tax deducted."),
    "period_not_over": _("The period isn't over: %(days)s days still to come are counted as "
                         "expected."),
    "no_check_out": _("%(days)s days have a check-in without a check-out: no time was deducted "
                      "for them."),
    "negative_net": _("Net pay is negative."),
    "off_cycle_no_tax": _("An off-cycle run deducts no income tax or social insurance."),
}
# Which feature each kind of amount belongs to.
AMOUNT_FEATURES = {"item": "pay_items", "incentive": "incentives", "penalty": "penalties",
                   "advance": "advances", "installment": "loans"}


@dataclass
class Line:
    code: str
    kind: str
    amount: Decimal
    taxable: bool = False
    label: str = ""  # a name (pay item, type); system lines use LINE_LABELS[code]
    quantity: Decimal | None = None
    rate: Decimal | None = None
    source: str = ""
    source_id: int | None = None
    slice: str = ""
    manual_id: int | None = None


@dataclass
class Issue:
    severity: str
    code: str
    params: dict = field(default_factory=dict)


@dataclass
class Slip:
    lines: list[Line] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def add(self, code: str, kind: str, amount: Decimal, **extra) -> None:
        amount = round_money(amount)
        if amount:
            self.lines.append(Line(code, kind, amount, **extra))

    def block(self, code: str, **params) -> None:
        self.issues.append(Issue(BLOCKING, code, params))

    def warn(self, code: str, **params) -> None:
        self.issues.append(Issue(WARNING, code, params))

    def total(self, kind: str) -> Decimal:
        return sum((line.amount for line in self.lines if line.kind == kind), ZERO)

    @property
    def taxable(self) -> Decimal:
        return sum((line.amount if line.kind == EARNING else -line.amount
                    for line in self.lines if line.taxable and line.kind != EMPLOYER), ZERO)


class Calculator:
    feature: str | None = None
    kinds: frozenset[str] = frozenset({REGULAR})

    def applies(self, data: PayslipInput) -> bool:
        return data.kind in self.kinds and (self.feature is None or self.feature in data.features)

    def run(self, data: PayslipInput, slip: Slip) -> None:
        raise NotImplementedError


def _attended(data: PayslipInput) -> tuple[PayDay, ...]:
    return data.days if data.attendance else ()


def _present(day: PayDay) -> bool:
    return day.status == "present"


# --- the calculators, in order -------------------------------------------------------------


class BasePay(Calculator):
    """Fixed salary: the salary for the full period, else the day rate × days employed (a month
    counted as 30 days, PayRole :587). Daily wage: paid days × the day's wage. Hourly wage:
    hours paid × the hour's wage."""

    def run(self, data, slip):
        if data.terms is None:
            slip.block("no_pay")
            return
        wage = data.terms.wage_type
        if wage != FIXED and not data.attendance:
            slip.block("needs_attendance")
            return
        if wage == FIXED:
            self._fixed(data, slip)
        elif wage == DAILY:
            paid = [d for d in data.days if _present(d) or d.status in PAID_AWAY
                    or (d.status == "leave" and d.paid)]
            slip.add("day_wage", EARNING, sum((d.terms.daily for d in paid), ZERO),
                     taxable=True, quantity=Decimal(len(paid)), rate=data.terms.daily)
        elif wage == HOURLY:
            minutes = ZERO
            for day in data.days:
                if _present(day):
                    cap = day.terms.hours_per_day * SIXTY if day.overtime else None
                    minutes += min(Decimal(day.worked_minutes), cap or day.worked_minutes)
                elif day.status in PAID_AWAY or (day.status == "leave" and day.paid):
                    minutes += day.terms.hours_per_day * SIXTY
            hours = minutes / SIXTY
            slip.add("hour_wage", EARNING, hours * data.terms.hourly, taxable=True,
                     quantity=round_money(hours), rate=data.terms.hourly)

    def _fixed(self, data, slip):
        days = data.days
        amount = sum((d.terms.daily for d in days), ZERO)
        if data.full_period:
            # A full month is worth the salary whatever its length: scale to 30 days.
            amount = amount * PERIOD_DAYS[data.pay_frequency] / data.period.days
            slip.add("salary", EARNING, amount, taxable=True)
        else:
            slip.add("salary", EARNING, amount, taxable=True, quantity=Decimal(len(days)),
                     rate=data.terms.daily)


class DaysNotPaid(Calculator):
    """A fixed salary loses the day rate for each absent day, excused absence and day of unpaid
    leave (PayRole: those days were simply not in the day-by-day pay)."""

    feature = "attendance"

    def run(self, data, slip):
        if data.terms is None or data.terms.wage_type != FIXED:
            return
        unpaid = [d for d in _attended(data)
                  if d.status in UNPAID_AWAY or (d.status == "leave" and not d.paid)]
        slip.add("days_not_paid", DEDUCTION, sum((d.terms.daily for d in unpaid), ZERO),
                 taxable=True, quantity=Decimal(len(unpaid)))
        upcoming = sum(1 for d in _attended(data) if d.status == "upcoming")
        if upcoming:
            slip.warn("period_not_over", days=upcoming)


class AbsencePenalty(Calculator):
    """An absent day costs (absence multiplier − 1) more days (PayRole :535)."""

    feature = "attendance"

    def run(self, data, slip):
        absent = [d for d in _attended(data) if d.status == "absent"]
        amount = sum((d.terms.daily * max(d.absence_multiplier - 1, ZERO) for d in absent), ZERO)
        slip.add("absence_penalty", DEDUCTION, amount, taxable=True,
                 quantity=Decimal(len(absent)))


class HolidayWork(Calculator):
    """A day worked on a public holiday or approved leave is paid × the holiday multiplier: the
    extra (multiplier − 1) days (PayRole :429)."""

    feature = "attendance"

    def run(self, data, slip):
        worked = [d for d in _attended(data) if _present(d) and (d.holiday or d.leave)]
        amount = sum((d.terms.daily * max(d.holiday_multiplier - 1, ZERO) for d in worked), ZERO)
        slip.add("holiday_work", EARNING, amount, taxable=True, quantity=Decimal(len(worked)))


def overtime_hours(day: PayDay) -> Decimal:
    """Paid overtime hours of a day: beyond the hours a day, or all of a marked day off (PayRole
    :415); none within the policy's "starts after"; bands, else whole hours rounded up (:419)."""
    if day.overtime is None or not _present(day) or day.missing_check_out:
        return ZERO
    over = day.worked_minutes
    if not day.marked_day_off:
        over -= int(day.terms.hours_per_day * SIXTY)
    if over <= 0 or over <= day.overtime.starts_after_minutes:
        return ZERO
    if day.overtime.bands:
        band = band_for(day.overtime.bands, over)
        return band.hours if band is not None else ZERO
    return Decimal(math.ceil(over / 60))


class OvertimePay(Calculator):
    feature = "overtime"

    def run(self, data, slip):
        hours = ZERO
        amount = ZERO
        for day in _attended(data):
            paid = overtime_hours(day)
            hours += paid
            amount += paid * day.terms.hourly * day.overtime_multiplier
        slip.add("overtime", EARNING, amount, taxable=True, quantity=hours)


class MissingTime(Calculator):
    """A working day short of its hours. Approved hourly leave covers missing time first, then
    the allowed early leave. With a lateness policy, lateness over the grace minutes is deducted
    by the band of the minutes late (PayRole :471); without one, the missing time as it is, at
    the hour rate (:462).
    Hourly wages are paid for hours worked, so nothing is deducted from them."""

    feature = "attendance"

    def run(self, data, slip):
        if data.terms is None or data.terms.wage_type == HOURLY:
            return
        missing, missing_amount = ZERO, ZERO
        late_hours, late_amount = ZERO, ZERO
        no_check_out = 0
        lateness_on = "lateness" in data.features
        for day in _attended(data):
            if not _present(day) or day.rest_day:
                continue
            if day.missing_check_out:
                no_check_out += 1
                continue
            short = int(day.terms.hours_per_day * SIXTY) - day.worked_minutes
            short -= min(max(short, 0), day.hourly_minutes)
            short -= min(day.early_minutes, day.early_leave_minutes)
            if short <= 0:
                continue
            if lateness_on and day.lateness is not None and not day.hourly_minutes:
                # Grace is a threshold: up to it nothing; beyond, the band of the minutes late.
                late = day.late_minutes
                band = (band_for(day.lateness.bands, late)
                        if late > day.lateness.grace_minutes else None)
                if band is not None and band.hours:
                    late_hours += band.hours
                    late_amount += band.hours * day.terms.hourly
                continue
            missing += Decimal(short)
            missing_amount += Decimal(short) / SIXTY * day.terms.hourly
        slip.add("missing_time", DEDUCTION, missing_amount, taxable=True,
                 quantity=round_money(missing / SIXTY))
        slip.add("lateness", DEDUCTION, late_amount, taxable=True, quantity=late_hours)
        if no_check_out:
            slip.warn("no_check_out", days=no_check_out)


class Amounts(Calculator):
    """Pay items, incentives, penalties, advances and installments allocated to the period, each
    of its feature; a per-day item × the days worked in its range (PayRole :321)."""

    kinds = frozenset({REGULAR, OFF_CYCLE})

    def run(self, data, slip):
        worked_days = [d.day for d in _attended(data) if _present(d) and not d.marked_day_off]
        for item in data.amounts:
            if AMOUNT_FEATURES[item.code] not in data.features:
                continue
            amount, quantity = item.amount, None
            if item.per_day:
                count = sum(1 for day in worked_days
                            if item.start <= day and (item.end is None or day <= item.end))
                amount, quantity = item.amount * count, Decimal(count)
            slip.add(item.code, EARNING if item.addition else DEDUCTION, amount,
                     taxable=item.taxable, label=item.label, quantity=quantity,
                     rate=item.amount if item.per_day else None, source=item.source,
                     source_id=item.source_id, slice=item.slice)


class ManualLines(Calculator):
    kinds = frozenset({REGULAR, OFF_CYCLE})

    def run(self, data, slip):
        for line in data.manual:
            slip.add("manual", EARNING if line.addition else DEDUCTION, line.amount,
                     taxable=line.taxable, label=line.label, manual_id=line.manual_id)


class SocialInsurance(Calculator):
    """The employee's share is deducted; the employer's is a cost, reported apart. No rates set:
    nothing is deducted and approval is blocked; rates set to 0 %: nothing, on purpose."""

    feature = "insurance"

    def run(self, data, slip):
        if not data.insured:
            return
        if data.insurance is None:
            slip.block("insurance_missing")
            return
        rates = data.insurance
        source = {"source": "policies.InsuranceRate", "source_id": rates.rates_id}
        slip.add("insurance_employee", DEDUCTION, rates.insured * rates.employee_rate / HUNDRED,
                 taxable=True, quantity=rates.insured, rate=rates.employee_rate, **source)
        slip.add("insurance_employer", EMPLOYER, rates.insured * rates.employer_rate / HUNDRED,
                 quantity=rates.insured, rate=rates.employer_rate, **source)


class IncomeTax(Calculator):
    """Tax on the period's taxable pay, annualized by periods a year, less the yearly exemption,
    by brackets, back to one period (PayRole :206, :617)."""

    feature = "income_tax"

    def run(self, data, slip):
        if data.tax is None:
            slip.warn("no_tax_table")
            return
        taxable = max(slip.taxable, ZERO)
        periods = Decimal(data.tax.periods_a_year)
        yearly = taxable * periods - data.tax.annual_exemption
        slip.add("income_tax", DEDUCTION, yearly_tax(yearly, data.tax.brackets) / periods,
                 quantity=round_money(taxable), source="policies.TaxTable",
                 source_id=data.tax.table_id)


class OffCycleNotice(Calculator):
    kinds = frozenset({OFF_CYCLE})

    def run(self, data, slip):
        slip.warn("off_cycle_no_tax")


CALCULATORS: tuple[Calculator, ...] = (
    BasePay(), DaysNotPaid(), AbsencePenalty(), HolidayWork(), OvertimePay(), MissingTime(),
    Amounts(), ManualLines(), SocialInsurance(), IncomeTax(), OffCycleNotice(),
)


@dataclass(frozen=True)
class Result:
    lines: tuple[Line, ...]
    issues: tuple[Issue, ...]
    earnings: Decimal
    deductions: Decimal
    employer_cost: Decimal

    @property
    def net(self) -> Decimal:
        return self.earnings - self.deductions

    @property
    def blocking(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == BLOCKING)


def calculate(data: PayslipInput) -> Result:
    slip = Slip()
    for severity, code, param in data.problems:
        slip.issues.append(Issue(severity, code, {"detail": param}))
    for calculator in CALCULATORS:
        if calculator.applies(data):
            calculator.run(data, slip)
    earnings, deductions = slip.total(EARNING), slip.total(DEDUCTION)
    if earnings - deductions < 0:
        slip.block("negative_net")
    return Result(tuple(slip.lines), tuple(slip.issues), earnings, deductions,
                  slip.total(EMPLOYER))


def issue_counts(issues) -> Counter:
    return Counter(issue.severity for issue in issues)
