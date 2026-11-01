"""Undo and redo on the company structure page.

A move isn't undone by moving back: that would add a row to the employee's history, and could not
bring back a row the move overwrote or a branch a department left. Each change keeps the before and
after of everything it touched, and going either way puts one of those back, only if things are
still as the change left them. If they aren't, newer work is never overwritten: the change is
dropped and the person is told. See docs/decisions/ADR-108-structure-undo.md."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.org.models import Department, DepartmentBranch
from apps.org.permissions import DEPARTMENT_MANAGE
from apps.org.services import add_department_branch, remove_department_branch

from .. import selectors
from ..models import Employee, EmployeeAssignment, StructureChange, StructureChangeState
from ..permissions import MANAGE
from ..validators import check_placement
from .employees import follow_assignment

KEPT = 30  # changes a member can go back through
ROW_FIELDS = ("branch_id", "department_id", "job_title", "position_id", "note", "ended_on",
              "leave_reason", "created_by_id")


def _row(employee_id: int, day: date) -> dict | None:
    row = EmployeeAssignment.objects.filter(employee_id=employee_id, effective_from=day).values(
        *ROW_FIELDS).first()
    if row and row["ended_on"]:
        row["ended_on"] = row["ended_on"].isoformat()
    return row


def _placed(department_id: int, branch_id: int) -> bool:
    return DepartmentBranch.objects.filter(department_id=department_id,
                                           branch_id=branch_id).exists()


class Recording:
    """What one change touches: told before the change, and saved after it. Without an actor nobody
    could undo it, so nothing is kept."""

    def __init__(self, actor, kind: str, **details):
        self.actor, self.kind, self.details = actor, kind, details
        self.rows: dict[tuple[int, date], dict | None] = {}
        self.placements: dict[tuple[int, int], bool] = {}

    def watch_people(self, people, day: date) -> None:
        for person in people:
            start = max(day, person.hired_on)
            self.rows[(person.pk, start)] = _row(person.pk, start)

    def watch_placement(self, department_id: int, branch_id: int) -> None:
        self.placements[(department_id, branch_id)] = _placed(department_id, branch_id)

    def save(self) -> None:
        rows = [{"employee": employee, "day": day.isoformat(), "before": before,
                 "after": _row(employee, day)} for (employee, day), before in self.rows.items()]
        placements = [{"department": department, "branch": branch, "before": before,
                       "after": _placed(department, branch)}
                      for (department, branch), before in self.placements.items()]
        rows = [row for row in rows if row["before"] != row["after"]]
        placements = [item for item in placements if item["before"] != item["after"]]
        if self.actor is None or not (rows or placements):
            return
        mine = StructureChange.objects.filter(created_by=self.actor.user)
        mine.filter(state=StructureChangeState.UNDONE).delete()  # nothing left to redo after this
        StructureChange.objects.create(created_by=self.actor.user, kind=self.kind,
                                       details=self.details, rows=rows, placements=placements)
        oldest = list(mine.order_by("-pk").values_list("pk", flat=True)[KEPT:])
        mine.filter(pk__in=oldest).delete()


def _changed_since() -> DomainError:
    return DomainError(_("This changed afterwards, so it can no longer be undone."),
                       code="STRUCTURE_CHANGED")


def _authorize(change: StructureChange, actor) -> None:
    """Their own change, with the permissions they hold today."""
    for row in change.rows:
        for side in (row["before"], row["after"]):
            if side:
                actor.require(MANAGE, branch=side["branch_id"])
    for item in change.placements:
        actor.require(DEPARTMENT_MANAGE, branch=item["branch"])


def _restore_row(employee: Employee | None, item: dict, now: str, then: str) -> None:
    day = date.fromisoformat(item["day"])
    if employee is None or _row(employee.pk, day) != item[now]:
        raise _changed_since()
    locks.ensure_open(employee.pk, day, date.max)
    if ((employee.left_on is not None and day > employee.left_on)
            or employee.assignments.filter(effective_from__gt=day,
                                           effective_from__lte=timezone.localdate()).exists()):
        raise _changed_since()
    target = item[then]
    if target is None:
        employee.assignments.filter(effective_from=day).delete()
        return
    if check_placement(employee, target["branch_id"], target["department_id"]):
        raise _changed_since()
    EmployeeAssignment.objects.update_or_create(employee=employee, effective_from=day,
                                                defaults=target)


def _restore(change: StructureChange, now: str, then: str) -> None:
    """A department returns to a branch before its people do, and leaves one after they have."""
    wanted = {item["department"] for item in change.placements}
    departments = Department.objects.in_bulk(wanted)
    if len(departments) != len(wanted) or any(
            _placed(item["department"], item["branch"]) != item[now] for item in change.placements):
        raise _changed_since()
    for item in change.placements:
        if item[then]:
            add_department_branch(departments[item["department"]], item["branch"])
    touched = Employee.objects.filter(pk__in={row["employee"] for row in change.rows})
    people = {person.pk: person
              for person in touched.select_for_update(of=("self",)).order_by("pk")}
    for row in change.rows:
        _restore_row(people.get(row["employee"]), row, now, then)
    for person in people.values():
        follow_assignment(person)
    for item in change.placements:
        if not item[then]:
            remove_department_branch(departments[item["department"]], item["branch"])


@transaction.atomic
def _switch(change_id: int, actor, state: str, next_state: str, now: str, then: str) -> dict:
    change = (StructureChange.objects.select_for_update()
              .filter(pk=change_id, created_by=actor.user, state=state).first())
    if change is None:
        raise NotFound(_("Not found."))
    _authorize(change, actor)
    label = selectors.change_label(change)
    try:
        with transaction.atomic():
            _restore(change, now, then)
    except (ValidationError, DomainError) as error:
        change.delete()  # no longer true, and refusing again would block what is behind it
        message = error.message if error.code == "PAYROLL_LOCKED" else _changed_since().message
        return {"done": False, "label": label, "message": message}
    change.state = next_state
    change.save(update_fields=["state", "updated_at"])
    return {"done": True, "label": label, "message": ""}


def undo(change_id: int, *, actor) -> dict:
    return _switch(change_id, actor, StructureChangeState.DONE, StructureChangeState.UNDONE,
                   "after", "before")


def redo(change_id: int, *, actor) -> dict:
    return _switch(change_id, actor, StructureChangeState.UNDONE, StructureChangeState.DONE,
                   "before", "after")
