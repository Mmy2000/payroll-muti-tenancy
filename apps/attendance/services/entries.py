"""A manager's entries for work days: worked (with times), absent, excused, or a day off.

An entry wins over the punches of its day without touching them, and clearing it brings the
punches back into force. Permissions follow the employee's branch (`attendance.day.manage`).
Times entered by hand are judged like clock times: lateness, early leave and overtime follow
from them and the employee's policies, and payroll locks apply.

`set_times_for_group` enters times for many employees at once (the same times, or each their
own), with a reason and a preview (apps/core/bulk.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from functools import partial

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import bulk, locks
from apps.core.errors import NotFound, invalid_fields
from apps.employees.models import Employee
from apps.employees.selectors import Group, resolve_group, visible_employees

from ..domain.days import Status
from ..domain.workday import times_on
from ..models import AttendanceDay, DayKind
from ..selectors import ScheduleHistory, evaluate
from ..validators import check_day

MANAGE = "attendance.day.manage"


@dataclass(frozen=True)
class DayEntryInput:
    kind: str
    check_in: time | None = None
    check_out: time | None = None
    note: str = ""
    # For "worked": take the times from each employee's shift instead of check_in/check_out.
    shift_times: bool = False


def _employees(employee_ids, actor) -> list[Employee]:
    ids = set(employee_ids)
    found = list(visible_employees(actor, MANAGE).filter(pk__in=ids)
                 .select_for_update(of=("self",)).order_by("pk"))
    if len(found) != len(ids):
        raise NotFound(_("Not found."))
    return found


def _times(employee: Employee, work_date: date, data: DayEntryInput):
    if data.kind != DayKind.WORKED:
        return None, None
    if data.shift_times:
        row = ScheduleHistory(employee.schedules.all()).on(work_date)
        if row is None:
            raise invalid_fields({"kind": [_("%(name)s has no working hours on that day.")
                                     % {"name": employee.name}]})
        start, end = row.starts_at, row.ends_at
    else:
        start, end = data.check_in, data.check_out
    return times_on(work_date, start, end, timezone.get_current_timezone())


def _save(employee: Employee, work_date: date, data: DayEntryInput, actor) -> AttendanceDay:
    if not (employee.hired_on <= work_date
            and (employee.left_on is None or work_date <= employee.left_on)):
        raise invalid_fields({"work_date": [_("%(name)s was not employed on that day.")
                                      % {"name": employee.name}]})
    if actor is not None:
        actor.require(MANAGE, branch=employee.branch_id)
    locks.ensure_open(employee.pk, work_date)
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
    check_day(data, work_date)
    with transaction.atomic():
        (employee,) = _employees([employee_id], actor)
        return _save(employee, work_date, data, actor)


def set_days(employee_ids: list[int], work_date: date, data: DayEntryInput, *,
             actor=None) -> list[AttendanceDay]:
    """The same entry for several employees (the daily sheet's "mark all")."""
    check_day(data, work_date)
    with transaction.atomic():
        return [_save(employee, work_date, data, actor)
                for employee in _employees(employee_ids, actor)]


def clear_day(employee_id: int, work_date: date, *, actor=None) -> None:
    with transaction.atomic():
        (employee,) = _employees([employee_id], actor)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        locks.ensure_open(employee.pk, work_date)
        AttendanceDay.objects.filter(employee=employee, work_date=work_date).delete()


# --- times for a group ---------------------------------------------------------------------


@dataclass(frozen=True)
class GroupTimesInput:
    group: Group
    work_date: date
    check_in: time | None
    check_out: time | None
    reason: str
    # {employee id: (check-in, check-out)} for those who came or left at other times.
    own_times: dict[int, tuple[time | None, time | None]] | None = None
    # Days some of them already have an entry by hand: replaced, or refused (the default).
    replace: bool = False


def _times_warnings(employee: Employee, work_date: date):
    def warn():
        day = evaluate([employee], work_date, work_date)[employee.pk][0]
        if day.source == "clock":
            yield _("The clock recorded this day (%(came)s); this entry wins over it.") % {
                "came": timezone.localtime(day.check_in).strftime("%H:%M")}
        if day.status in (Status.DAY_OFF, Status.HOLIDAY) or day.rest_day:
            yield _("Not a working day for them: the time counts as work on a rest day.")
        if day.leave:
            yield _("On approved leave that day (%(what)s): paid at the holiday rate.") % {
                "what": day.leave}

    return warn


def _set_times(employee: Employee, data: GroupTimesInput, times, actor) -> AttendanceDay:
    check_in, check_out = times
    errors = {}
    if check_in is None:
        errors["check_in"] = [_("Enter the time they came.")]
    if check_out is None:
        errors["check_out"] = [_("Enter the time they left.")]
    if not data.replace and AttendanceDay.objects.filter(
            employee=employee, work_date=data.work_date).exists():
        errors["work_date"] = [_("Already entered by hand for that day.")]
    if errors:
        raise invalid_fields(errors)
    return _save(employee, data.work_date, DayEntryInput(
        kind=DayKind.WORKED, check_in=check_in, check_out=check_out, note=data.reason), actor)


def set_times_for_group(data: GroupTimesInput, *, save: bool = False,
                        skip_failed: bool = False, actor=None) -> bulk.Outcome:
    """Each employee of the group worked the day, at the given times (or their own)."""
    if actor is not None:
        actor.require(MANAGE)
    if not data.reason.strip():
        raise invalid_fields({"reason": [_("Say why the times are entered by hand.")]})
    check_day(DayEntryInput(kind=DayKind.WORKED, check_in=data.check_in or time()),
           data.work_date)
    own = data.own_times or {}
    with transaction.atomic():
        people = resolve_group(data.group, on=data.work_date, actor=actor, permission=MANAGE)
        unknown = set(own) - {employee.pk for employee in people}
        if unknown:
            raise invalid_fields(
                {"own_times": [_("Times are given for someone not in the group.")]})
        items = []
        for employee in people:
            times = own.get(employee.pk, (data.check_in, data.check_out))
            detail = " – ".join(t.strftime("%H:%M") if t else "?" for t in times)
            items.append(bulk.Item(employee, detail,
                                   partial(_set_times, employee, data, times, actor),
                                   warn=_times_warnings(employee, data.work_date)))
        return bulk.run(items, save=save, skip_failed=skip_failed)
