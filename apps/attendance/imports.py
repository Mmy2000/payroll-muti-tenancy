"""Importing clock punches from Excel (PayRole: zkk/methods.py), all or nothing
(apps.core.imports). One row per employee and day: the time they came and, if known, the time
they left. A punch already on record (the same file imported twice) is not added again."""

from __future__ import annotations

from datetime import date

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.imports import CellError, Cells, Column, SheetImport
from apps.employees.services import visible_employees

from .domain.workday import times_on
from .models import Punch, PunchSource

PERMISSION = "attendance.import"


class PunchImport(SheetImport):
    permission = PERMISSION
    sheet_title = "attendance"
    columns = [
        Column("employee_code", _lazy("Employee code"), True, 101),
        Column("date", _lazy("Date"), True, date(2026, 1, 4)),
        Column("check_in", _lazy("Came (HH:MM)"), True, "09:02"),
        Column("check_out", _lazy("Left (HH:MM)"), False, "17:10"),
    ]

    def prepare(self):
        self.employees = {e.code: e for e in visible_employees(self.actor, PERMISSION)}
        self.zone = timezone.get_current_timezone()
        self.today = timezone.localdate()

    def import_row(self, cells: Cells) -> None:
        employee = self.employees.get(cells.integer("employee_code"))
        if employee is None:
            raise CellError("employee_code", _("No employee you can manage has this code."))
        day = cells.required("date", cells.date("date"), _("Enter the date."))
        if day > self.today:
            raise CellError("date", _("Must not be in the future."))
        if day < employee.hired_on or (employee.left_on is not None and day > employee.left_on):
            raise CellError("date", _("The employee isn't employed on that day."))
        came = cells.required("check_in", cells.time("check_in"), _("Enter a time as HH:MM."))
        moments = [m for m in times_on(day, came, cells.time("check_out"), self.zone) if m]
        for moment in moments:
            Punch.objects.get_or_create(
                employee=employee, at=moment,
                defaults={"source": PunchSource.IMPORT,
                          "created_by": getattr(self.actor, "user", None)})
