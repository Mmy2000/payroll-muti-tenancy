"""Importing employee cards from Excel (PayRole: GHA12 "upload cards"), all or nothing
(apps.core.imports). Every row goes through `create_employee`, exactly like the form."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.imports import CellError, Cells, Column, SheetImport
from apps.org.models import Branch, Department

from . import services
from .models import PayFrequency, WageType

DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
        "الاثنين": 0, "الإثنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الاربعاء": 2, "الخميس": 3,
        "الجمعة": 4, "الجمعه": 4, "السبت": 5, "الأحد": 6, "الاحد": 6}


def weekdays(cells: Cells, key: str) -> list[int]:
    """"fri, sat" (English, any length from three letters) or Arabic day names."""
    text = cells.text(key).replace("،", ",")
    days = []
    for part in filter(None, (p.strip().lower() for p in text.split(","))):
        day = DAYS.get(part[:3]) if part[:3] in DAYS else DAYS.get(part)
        if day is None:
            raise CellError(key, _("Unknown day: %(day)s") % {"day": part})
        days.append(day)
    return days


class EmployeeImport(SheetImport):
    permission = "employees.employee.import"
    sheet_title = "employees"
    columns = [
        Column("code", _lazy("Employee code"), True, 101),
        Column("name", _lazy("Name"), True, "Ahmed Ali"),
        Column("branch_code", _lazy("Branch code"), True, 1),
        Column("department_code", _lazy("Department code"), False, ""),
        Column("job_title", _lazy("Job title"), False, "Accountant"),
        Column("hired_on", _lazy("Hiring date"), True, date(2024, 1, 1)),
        Column("national_id", _lazy("National ID"), False, ""),
        Column("gender", _lazy("Gender (male / female)"), False, "male"),
        Column("birth_date", _lazy("Birth date"), False, ""),
        Column("phone", _lazy("Phone"), False, ""),
        Column("insurance_number", _lazy("Insurance number"), False, ""),
        Column("wage_type", _lazy("Pay counted as (fixed / daily / hourly)"), False, "fixed"),
        Column("pay_frequency", _lazy("Paid (monthly / biweekly / weekly)"), False, "monthly"),
        Column("salary", _lazy("Salary"), True, 6000),
        Column("hours_per_day", _lazy("Hours a day"), False, 8),
        Column("insured_salary", _lazy("Insured salary"), False, ""),
        Column("annual_leave_days", _lazy("Annual leave days"), False, 21),
        Column("starts_at", _lazy("Shift starts (HH:MM)"), True, "09:00"),
        Column("ends_at", _lazy("Shift ends (HH:MM)"), True, "17:00"),
        Column("days_off", _lazy("Days off (e.g. fri, sat)"), False, "fri"),
    ]

    def prepare(self):
        self.branches = dict(Branch.objects.filter(is_active=True).values_list("code", "pk"))
        self.departments = dict(Department.objects.filter(is_active=True)
                                .values_list("code", "pk"))

    def _lookup(self, cells: Cells, key: str, table: dict, message: str, *, optional=False):
        code = cells.integer(key)
        if code is None and optional:
            return None
        if code not in table:
            raise CellError(key, message)
        return table[code]

    def import_row(self, cells: Cells) -> None:
        card = services.EmployeeInput(
            code=cells.integer("code", 0), name=cells.text("name"),
            branch_id=self._lookup(cells, "branch_code", self.branches,
                                   _("No active branch has this code.")),
            department_id=self._lookup(cells, "department_code", self.departments,
                                       _("No active department has this code."), optional=True),
            hired_on=cells.required("hired_on", cells.date("hired_on"),
                                    _("Enter the hiring date.")),
            job_title=cells.text("job_title"), national_id=cells.text("national_id"),
            gender=cells.text("gender").lower(), birth_date=cells.date("birth_date"),
            phone=cells.text("phone"), insurance_number=cells.text("insurance_number"))
        pay = services.CompensationInput(
            effective_from=None,
            salary=cells.required("salary", cells.decimal("salary"), _("Enter the salary.")),
            wage_type=cells.text("wage_type").lower() or WageType.FIXED,
            pay_frequency=cells.text("pay_frequency").lower() or PayFrequency.MONTHLY,
            hours_per_day=cells.decimal("hours_per_day", Decimal(8)),
            insured_salary=cells.decimal("insured_salary"),
            annual_leave_days=cells.integer("annual_leave_days", 21))
        schedule = services.ScheduleInput(
            effective_from=None,
            starts_at=cells.required("starts_at", cells.time("starts_at"),
                                     _("Enter a time as HH:MM.")),
            ends_at=cells.required("ends_at", cells.time("ends_at"), _("Enter a time as HH:MM.")),
            days_off=weekdays(cells, "days_off"))
        services.create_employee(card, pay, schedule, actor=self.actor)
