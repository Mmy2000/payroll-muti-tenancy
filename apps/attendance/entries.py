"""A manager's entries for work days: worked (with times), absent, excused, or a day off.

An entry wins over the punches of its day without touching them, and clearing it brings the
punches back into force. Permissions follow the employee's branch (`attendance.day.manage`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, ValidationError
from apps.employees.models import Employee
from apps.employees.services import visible_employees

from .domain.workday import times_on
from .models import AttendanceDay, DayKind
from .selectors import ScheduleHistory

MANAGE = "attendance.day.manage"
# Kinds that may be entered for a day still to come (planning a day off or an excused absence).
PLANNABLE = {DayKind.EXCUSED, DayKind.DAY_OFF}


@dataclass(frozen=True)
class DayEntryInput:
    kind: str
    check_in: time | None = None
    check_out: time | None = None
    note: str = ""
    # For "worked": take the times from each employee's shift instead of check_in/check_out.
    shift_times: bool = False


def _invalid(fields: dict) -> ValidationError:
    return ValidationError(_("Please correct the highlighted fields."), fields=fields)


def _employees(employee_ids, actor) -> list[Employee]:
    ids = set(employee_ids)
    found = list(visible_employees(actor, MANAGE).filter(pk__in=ids)
                 .select_for_update(of=("self",)).order_by("pk"))
    if len(found) != len(ids):
        raise NotFound(_("Not found."))
    return found


def _check(data: DayEntryInput, work_date: date) -> None:
    errors = {}
    if data.kind not in DayKind.values:
        errors["kind"] = [_("Choose what happened that day.")]
    elif work_date > timezone.localdate() and data.kind not in PLANNABLE:
        errors["work_date"] = [_("Only a day off or an excused absence can be entered ahead.")]
    elif data.kind == DayKind.WORKED and not data.shift_times and data.check_in is None:
        errors["check_in"] = [_("Enter the time they came.")]
    if errors:
        raise _invalid(errors)


def _times(employee: Employee, work_date: date, data: DayEntryInput):
    if data.kind != DayKind.WORKED:
        return None, None
    if data.shift_times:
        row = ScheduleHistory(employee.schedules.all()).on(work_date)
        if row is None:
            raise _invalid({"kind": [_("%(name)s has no working hours on that day.")
                                     % {"name": employee.name}]})
        start, end = row.starts_at, row.ends_at
    else:
        start, end = data.check_in, data.check_out
    return times_on(work_date, start, end, timezone.get_current_timezone())


def _save(employee: Employee, work_date: date, data: DayEntryInput, actor) -> AttendanceDay:
    if not (employee.hired_on <= work_date
            and (employee.left_on is None or work_date <= employee.left_on)):
        raise _invalid({"work_date": [_("%(name)s was not employed on that day.")
                                      % {"name": employee.name}]})
    if actor is not None:
        actor.require(MANAGE, branch=employee.branch_id)
    check_in, check_out = _times(employee, work_date, data)
    user = getattr(actor, "user", None)
    entry, _created = AttendanceDay.objects.update_or_create(
        employee=employee, work_date=work_date,
        defaults={"kind": data.kind, "check_in": check_in, "check_out": check_out,
                  "note": data.note.strip(), "updated_by": user},
        create_defaults={"kind": data.kind, "check_in": check_in, "check_out": check_out,
                         "note": data.note.strip(), "created_by": user, "updated_by": user})
    return entry


def set_day(employee_id: int, work_date: date, data: DayEntryInput, *,
            actor=None) -> AttendanceDay:
    _check(data, work_date)
    with transaction.atomic():
        (employee,) = _employees([employee_id], actor)
        return _save(employee, work_date, data, actor)


def set_days(employee_ids: list[int], work_date: date, data: DayEntryInput, *,
             actor=None) -> list[AttendanceDay]:
    """The same entry for several employees (the daily sheet's "mark all")."""
    _check(data, work_date)
    with transaction.atomic():
        return [_save(employee, work_date, data, actor)
                for employee in _employees(employee_ids, actor)]


def clear_day(employee_id: int, work_date: date, *, actor=None) -> None:
    with transaction.atomic():
        (employee,) = _employees([employee_id], actor)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        AttendanceDay.objects.filter(employee=employee, work_date=work_date).delete()
