"""The report registry: every report is a class with filters, the permission that already guards
its data, and a `run` that returns tables. One screen and every export (apps/reports/exporters.py)
serve them all; a report supplies data only.

    @register
    class Advances(Report):
        code, section = "advances", "pay"
        permission = "loans.advance.view"     # who may read it, and in which branches
        filters = (*DATE_FILTERS, BRANCH_FILTER, EMPLOYEE_FILTER)
        def run(self, params, scope): ...     # → [Table(...)]

A report uses the permission of the screen its data comes from (payroll runs, attendance,
loans…), so whoever may see the data may see the report, in the same branches, and a feature
switched off hides its reports with it. Exporting is a permission of its own (`reports.export`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core import months

REPORTS: dict[str, type[Report]] = {}


def register(report_class):
    if report_class.code in REPORTS:
        raise ValueError(f"Report {report_class.code} registered twice")
    REPORTS[report_class.code] = report_class
    return report_class


# kind → decimal places (None: not a number). Minutes are whole numbers shown as h:mm.
KINDS = {"text": None, "code": None, "date": None, "int": 0, "money": 2, "qty": 2, "pct": 1,
         "minutes": 0}


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"

    @property
    def places(self):
        return KINDS[self.kind]

    @property
    def numeric(self) -> bool:
        return self.places is not None


# A row may carry "_style" (heading, subtotal or total) and "_urls" ({column key: address}).
ROW_STYLES = ("heading", "subtotal", "total")


@dataclass
class Table:
    title: str
    columns: list[Column]
    rows: list[dict] = field(default_factory=list)
    totals: dict | None = None  # same keys as the rows; shown as the last line
    note: str = ""

    def add_totals(self, label_key: str, label: str, *, skip: tuple[str, ...] = ()) -> Table:
        """Sum every numeric column (but percentages and `skip`)."""
        totals = {label_key: label}
        for column in self.columns:
            if column.numeric and column.kind != "pct" and column.key not in skip:
                totals[column.key] = sum((row.get(column.key) or 0 for row in self.rows),
                                         Decimal(0) if column.kind != "minutes" else 0)
        self.totals = totals
        return self


@dataclass(frozen=True)
class Filter:
    key: str
    kind: str  # date | month | year | branch | department | employee | choice
    label: str = ""
    # (value, label) pairs, or a function returning them when the report opens.
    choices: tuple[tuple[str, str], ...] | object = ()
    default: str = ""


@dataclass
class Params:
    """Parsed filter values: dates (date_from defaults to the month's first day, others to
    today), months (their first day), years, the chosen branch / department / employee (or
    None for all), choices."""

    values: dict

    def date(self, key: str) -> date:
        raw = self.values.get(key)
        return raw if isinstance(raw, date) else timezone.localdate()

    def get(self, key: str, default=None):
        return self.values.get(key, default)


@dataclass(frozen=True)
class Scope:
    """What the reader may see: the branches of the report's permission (None: all), and the
    filters' branch, department and employee."""

    branches: frozenset[int] | None
    params: Params
    actor: object = None

    def employees(self, *, related=("branch", "department")):
        from apps.employees.models import Employee

        people = Employee.objects.select_related(*related).order_by("code")
        if self.branches is not None:
            people = people.filter(branch_id__in=self.branches)
        for key, column in (("branch", "branch"), ("department", "department"),
                            ("employee", "pk")):
            chosen = self.params.get(key)
            if chosen is not None:
                people = people.filter(**{column: chosen.pk})
        return people

    def can(self, code: str) -> bool:
        return self.actor is None or self.actor.can(code)


SECTIONS = (("payroll", _("Payroll"), "calculator"),
            ("attendance", _("Attendance and leave"), "clock"),
            ("pay", _("Loans, advances, incentives and items"), "hand-coins"),
            ("people", _("People"), "users"))
MAX_DAYS = 366


class Report:
    code = ""
    title = ""
    description = ""
    section = "payroll"  # where the reports page lists it (SECTIONS)
    permission = ""  # an existing permission: who may read this data, in which branches
    filters: tuple[Filter, ...] = ()
    max_days = MAX_DAYS  # the longest date range (a day-by-day report asks for less)

    def __init__(self):
        self.filters = tuple(replace(spec, choices=tuple(spec.choices()))
                             if callable(spec.choices) else spec for spec in type(self).filters)

    def parse(self, query, *, branches, departments, employees) -> Params:
        """Filter values from the query string, limited to what the reader may see."""
        today = timezone.localdate()
        values = {}
        for spec in self.filters:
            raw = (query.get(spec.key) or "").strip()
            if spec.kind == "date":
                fallback = today.replace(day=1) if spec.key == "date_from" else today
                try:
                    values[spec.key] = date.fromisoformat(raw) if raw else fallback
                except ValueError:
                    values[spec.key] = fallback
            elif spec.kind == "month":
                values[spec.key] = months.parse(raw, today)
            elif spec.kind == "year":
                values[spec.key] = int(raw) if raw.isdigit() and 2000 <= int(raw) <= 2100 \
                    else today.year
            elif spec.kind in ("branch", "department", "employee"):
                options = {"branch": branches, "department": departments,
                           "employee": employees}[spec.kind]
                values[spec.key] = options.filter(pk=raw).first() if raw.isdigit() else None
            else:
                keys = {key for key, _label in spec.choices}
                values[spec.key] = raw if raw in keys else spec.default
        start, end = values.get("date_from"), values.get("date_to")
        if start and end and start > end:
            values["date_from"], values["date_to"] = start, end = end, start
        if start and end and (end - start).days >= self.max_days:
            values["date_from"] = end - timedelta(days=self.max_days - 1)
        return Params(values)

    def run(self, params: Params, scope: Scope) -> list[Table]:
        raise NotImplementedError


DATE_FILTERS = (Filter("date_from", "date", _("From")), Filter("date_to", "date", _("To")))
BRANCH_FILTER = Filter("branch", "branch", _("Branch"))
DEPARTMENT_FILTER = Filter("department", "department", _("Department"))
EMPLOYEE_FILTER = Filter("employee", "employee", _("Employee"))
WHO_FILTERS = (BRANCH_FILTER, DEPARTMENT_FILTER, EMPLOYEE_FILTER)
