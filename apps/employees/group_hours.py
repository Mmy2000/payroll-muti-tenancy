"""New working hours for a group at once (PayRole GHA18 changed a group's shift by overwriting
each card), with a preview (apps/core/bulk.py).

The change starts on a date, for good or until a last day; after that last day each employee
goes back to the hours they had. Nothing earlier is rewritten: schedules are effective-dated,
so past days keep their hours, and `change_schedule` refuses a date an approved payroll covers.
Each employee keeps their own days off, policies and early-leave allowance unless the change
sets days off for everyone.

A change of hours already planned inside the range would be overridden by the return to the
old hours, so such an employee's row fails; one planned after the change is kept and said.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, time, timedelta

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import bulk
from apps.core.errors import ValidationError
from apps.core.history import in_effect

from .models import Employee, WorkSchedule
from .permissions import MANAGE
from .services import ScheduleInput, change_schedule
from .targets import Group, resolve_group


@dataclass(frozen=True)
class GroupHoursInput:
    group: Group
    effective_from: date
    starts_at: time
    ends_at: time
    until: date | None = None  # the last day of the new hours; None: from then on
    days_off: tuple[int, ...] | None = None  # None: each keeps their own
    note: str = ""


def _same_hours(row: WorkSchedule, effective_from: date, note: str) -> ScheduleInput:
    return ScheduleInput(effective_from=effective_from, starts_at=row.starts_at,
                         ends_at=row.ends_at, days_off=list(row.days_off),
                         lateness_policy_id=row.lateness_policy_id,
                         overtime_policy_id=row.overtime_policy_id,
                         early_leave_minutes=row.early_leave_minutes, note=note)


def _change(employee: Employee, data: GroupHoursInput, actor) -> None:
    current = in_effect(employee.schedules.all(), data.effective_from)
    if current is None:
        message = _("They have no working hours on that day yet.")
        raise ValidationError(message, fields={"effective_from": [message]})
    back_on = data.until + timedelta(days=1) if data.until else None
    if back_on is not None:
        planned = employee.schedules.filter(effective_from__gt=data.effective_from,
                                            effective_from__lte=data.until).first()
        if planned is not None:
            message = (_("Their hours already change on %(day)s, inside this range.")
                       % {"day": planned.effective_from})
            raise ValidationError(message, fields={"until": [message]})
    previous = in_effect(employee.schedules.all(), back_on) if back_on else None
    new = replace(_same_hours(current, data.effective_from, data.note),
                  starts_at=data.starts_at, ends_at=data.ends_at)
    if data.days_off is not None:
        new = replace(new, days_off=list(data.days_off))
    change_schedule(employee.pk, new, actor=actor)
    if back_on is not None and previous.effective_from != back_on and (
            employee.left_on is None or back_on <= employee.left_on):
        change_schedule(employee.pk, _same_hours(
            previous, back_on, _("Back to the usual hours")), actor=actor)


def _warnings(employee: Employee, data: GroupHoursInput):
    def warn():
        later = employee.schedules.filter(effective_from__gt=data.until or data.effective_from
                                          ).order_by("effective_from").first()
        if later is not None:
            yield _("Their hours change again on %(day)s; that change stays.") % {
                "day": later.effective_from}
        if employee.left_on is not None and data.until and data.until > employee.left_on:
            yield _("They leave on %(day)s.") % {"day": employee.left_on}

    return warn


def change_hours_for_group(data: GroupHoursInput, *, save: bool = False,
                           skip_failed: bool = False, actor=None) -> bulk.Outcome:
    if actor is not None:
        actor.require(MANAGE)
    errors = {}
    if data.starts_at == data.ends_at:
        errors["ends_at"] = [_("The shift must end at another time than it starts.")]
    if data.until is not None and data.until < data.effective_from:
        errors["until"] = [_("Must not be before the first day.")]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    detail = f"{data.starts_at:%H:%M}–{data.ends_at:%H:%M}"
    with transaction.atomic():
        people = resolve_group(data.group, on=data.effective_from, actor=actor,
                               permission=MANAGE)
        items = [bulk.Item(employee, detail, lambda e=employee: _change(e, data, actor),
                           warn=_warnings(employee, data)) for employee in people]
        return bulk.run(items, save=save, skip_failed=skip_failed)
