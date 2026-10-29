"""Everything one payslip is calculated from, as plain values (apps.payroll.gather builds them
from the database). The engine reads only these, and they are what an approved payslip keeps as
its snapshot (`to_snapshot`)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.employees.domain.rates import PayTerms
from apps.policies.domain.bands import Band
from apps.policies.domain.tax import Bracket

from .periods import Period

REGULAR, OFF_CYCLE = "regular", "off_cycle"


@dataclass(frozen=True)
class Lateness:
    grace_minutes: int
    bands: tuple[Band, ...]


@dataclass(frozen=True)
class Overtime:
    starts_after_minutes: int
    bands: tuple[Band, ...]


@dataclass(frozen=True)
class PayDay:
    """One day of the period, with what attendance found and the rates in effect that day."""

    day: date
    status: str  # apps.attendance.domain.days.Status
    terms: PayTerms
    overtime_multiplier: Decimal
    absence_multiplier: Decimal
    holiday_multiplier: Decimal
    rest_day: bool = False
    marked_day_off: bool = False
    holiday: bool = False
    leave: bool = False  # approved leave covers the day
    paid: bool = True  # for days away: is the day paid?
    worked_minutes: int = 0
    late_minutes: int = 0
    early_minutes: int = 0
    missing_check_out: bool = False
    hourly_minutes: int = 0  # approved hourly leave
    early_leave_minutes: int = 0  # allowed by the schedule
    lateness: Lateness | None = None
    overtime: Overtime | None = None


@dataclass(frozen=True)
class Amount:
    """Something added or deducted, already allocated to the period (gather), with its source so
    approval can record it as paid. `per_day`: the amount is for each day worked from `start` to
    `end` (the engine counts the days)."""

    code: str  # "item", "incentive", "penalty", "advance", "installment"
    label: str
    amount: Decimal
    addition: bool
    taxable: bool
    source: str  # "app.Model"
    source_id: int
    slice: str = ""  # which share of a recurring source ("2026-10-01..2026-10-31")
    per_day: bool = False
    start: date | None = None
    end: date | None = None


@dataclass(frozen=True)
class ManualLine:
    label: str
    amount: Decimal
    addition: bool
    taxable: bool
    manual_id: int


@dataclass(frozen=True)
class Insurance:
    insured: Decimal  # the insured salary allocated to the period, within the caps
    employee_rate: Decimal  # percent
    employer_rate: Decimal  # percent
    rates_id: int


@dataclass(frozen=True)
class Tax:
    annual_exemption: Decimal
    brackets: tuple[Bracket, ...]
    periods_a_year: int
    table_id: int


@dataclass(frozen=True)
class PayslipInput:
    employee_id: int
    employee_name: str
    kind: str  # REGULAR or OFF_CYCLE
    period: Period
    pay_frequency: str
    employed: Period | None  # the days of the period the employee was employed
    terms: PayTerms | None  # in effect at the end of the employed days
    features: frozenset[str]
    today: date
    days: tuple[PayDay, ...] = ()
    attendance: bool = False  # days come from attendance (the feature is on)
    amounts: tuple[Amount, ...] = ()
    manual: tuple[ManualLine, ...] = ()
    insured: bool = False  # the employee has an insured salary
    insurance: Insurance | None = None
    tax: Tax | None = None
    problems: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)  # found by gather

    @property
    def full_period(self) -> bool:
        return self.employed == self.period


def _plain(value):
    if isinstance(value, Decimal | date):
        return str(value)
    if isinstance(value, frozenset | set):
        return sorted(value)
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def to_snapshot(data: PayslipInput) -> dict:
    """The input as JSON-ready values (Decimals and dates as strings)."""
    return _plain(dataclasses.asdict(data))
