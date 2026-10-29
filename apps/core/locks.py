"""What an approved payroll has paid is locked (docs/payroll-design.md §6). Lower apps (attendance,
leave, loans, incentives, pay items…) must refuse to change it, but may not import payroll, which
sits above them. So payroll registers its answers here when it starts (dependency inversion), and
those apps ask through `ensure_open` / `ensure_unpaid`:

    from apps.core import locks
    locks.ensure_unpaid("loans.Advance", advance.pk)               # paid by a payslip?
    locks.ensure_open(employee.pk, start, end)                      # days covered by a payslip?
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from django.utils.translation import gettext as _

from .errors import DomainError

# (employee id, first day, last day) → True if an approved or paid payslip covers any of them.
PeriodCheck = Callable[[int, date, date], bool]
# (source label "app.Model", object id) → True if an approved or paid payslip used it.
SourceCheck = Callable[[str, int], bool]

_period_checks: list[PeriodCheck] = []
_source_checks: list[SourceCheck] = []


def register(*, period: PeriodCheck | None = None, source: SourceCheck | None = None) -> None:
    if period is not None:
        _period_checks.append(period)
    if source is not None:
        _source_checks.append(source)


def period_locked(employee_id: int, start: date, end: date | None = None) -> bool:
    return any(check(employee_id, start, end or start) for check in _period_checks)


def source_locked(label: str, object_id: int) -> bool:
    return any(check(label, object_id) for check in _source_checks)


def ensure_open(employee_id: int, start: date, end: date | None = None) -> None:
    if period_locked(employee_id, start, end):
        raise DomainError(_("An approved payroll already covers these days. Correct it through "
                            "the payroll (reverse it, or adjust in the next run)."),
                          code="PAYROLL_LOCKED")


def ensure_unpaid(label: str, object_id: int) -> None:
    if source_locked(label, object_id):
        raise DomainError(_("An approved payroll already paid this. Correct it through the "
                            "payroll (reverse it, or adjust in the next run)."),
                          code="PAYROLL_LOCKED")
