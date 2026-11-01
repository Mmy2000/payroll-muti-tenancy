"""Reorganising the company: people between departments and branches, and a department between
branches. Every move is dated and goes on the employee's assignments, so earlier days keep where
they were, and all of one move happens or none of it does."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.errors import DomainError, NotFound, invalid_fields
from apps.org.models import Branch, Department
from apps.org.permissions import DEPARTMENT_MANAGE
from apps.org.services import add_department_branch, remove_department_branch

from ..models import Employee, EmployeeAssignment, StructureChangeKind
from ..permissions import MANAGE
from ..selectors import visible_employees, working_in
from ..validators import check_placement
from .employees import follow_assignment
from .structure_history import Recording


def _place(employee: Employee, branch_id: int, department_id: int | None, day: date, note: str,
           actor) -> None:
    """One employee, from `day` (or their hiring date, if that is later). A second move on the same
    day replaces the first."""
    start = max(day, employee.hired_on)
    locks.ensure_open(employee.pk, start, date.max)
    if employee.left_on is not None and start > employee.left_on:
        raise invalid_fields({"effective_from": [_("Must not be after the day they left.")]})
    if employee.assignments.filter(effective_from__gt=start,
                                   effective_from__lte=timezone.localdate()).exists():
        raise invalid_fields({"effective_from": [
            _("%(name)s already moved after this date.") % {"name": employee.name}]})
    errors = check_placement(employee, branch_id, department_id)
    if errors:
        raise invalid_fields(errors)
    EmployeeAssignment.objects.update_or_create(
        employee=employee, effective_from=start,
        defaults={"branch_id": branch_id, "department_id": department_id, "note": note.strip(),
                  "job_title": employee.job_title, "position_id": employee.position_id,
                  "created_by": getattr(actor, "user", None)})
    follow_assignment(employee)


def _place_name(branch_id: int, department_id: int | None = None) -> str:
    names = [Branch.objects.get(pk=branch_id).name]
    if department_id is not None:
        names.insert(0, Department.objects.get(pk=department_id).name)
    return " · ".join(names)


def _require_people(actor, *branch_ids) -> None:
    if actor is not None:
        for branch_id in branch_ids:
            actor.require(MANAGE, branch=branch_id)


def _require_departments(actor, *branch_ids) -> None:
    if actor is not None:
        for branch_id in branch_ids:
            actor.require(DEPARTMENT_MANAGE, branch=branch_id)


def _not_ahead(day: date) -> None:
    """A department leaves a branch now: ahead of time, its people would still be there."""
    if day > timezone.localdate():
        raise invalid_fields({"effective_from": [_("Choose today or an earlier day.")]})


def _department(department_id: int) -> Department:
    department = Department.objects.filter(pk=department_id).first()
    if department is None:
        raise NotFound(_("Not found."))
    return department


def _in_branch(department: Department, branch_id: int) -> None:
    if not department.placements.filter(branch_id=branch_id).exists():
        raise NotFound(_("Not found."))


@transaction.atomic
def move_people(employee_ids: list[int], branch_id: int, department_id: int | None, day: date, *,
                note: str = "", actor=None) -> int:
    people = list(visible_employees(actor, MANAGE).filter(pk__in=set(employee_ids))
                  .select_for_update(of=("self",)).order_by("pk"))
    if len(people) != len(set(employee_ids)):
        raise NotFound(_("Not found."))
    _require_people(actor, branch_id, *{person.branch_id for person in people})
    recording = Recording(actor, StructureChangeKind.MOVE_PEOPLE, count=len(people),
                          name=people[0].name if people else "",
                          place=_place_name(branch_id, department_id))
    recording.watch_people(people, day)
    for person in people:
        _place(person, branch_id, department_id, day, note, actor)
    recording.save()
    return len(people)


@transaction.atomic
def move_department(department_id: int, from_branch_id: int, to_branch_id: int, day: date, *,
                    actor=None) -> int:
    """The department leaves one branch for another, and its people there go with it."""
    if from_branch_id == to_branch_id:
        raise invalid_fields({"branch_id": [_("Choose another branch.")]})
    _not_ahead(day)
    department = _department(department_id)
    _in_branch(department, from_branch_id)
    _require_departments(actor, from_branch_id, to_branch_id)
    people = list(working_in(from_branch_id, department_id).select_for_update(of=("self",))
                  .order_by("pk"))
    if people:
        _require_people(actor, from_branch_id, to_branch_id)
    recording = Recording(actor, StructureChangeKind.MOVE_DEPARTMENT, name=department.name,
                          place=_place_name(to_branch_id))
    recording.watch_people(people, day)
    recording.watch_placement(department_id, from_branch_id)
    recording.watch_placement(department_id, to_branch_id)
    add_department_branch(department, to_branch_id)
    for person in people:
        _place(person, to_branch_id, department_id, day, "", actor)
    remove_department_branch(department, from_branch_id)
    recording.save()
    return len(people)


@transaction.atomic
def remove_department(department_id: int, branch_id: int, move_to: int | None, day: date, *,
                      actor=None) -> int:
    """The department stops operating in a branch. Its people there stay in the branch, in
    `move_to` or in no department. A department is always somewhere: its last branch stays."""
    _not_ahead(day)
    department = _department(department_id)
    _in_branch(department, branch_id)
    _require_departments(actor, branch_id)
    if department.placements.count() == 1:
        raise DomainError(_("This is the department's only branch. Move it to another branch, or "
                            "deactivate it."), code="ORG_LAST_BRANCH")
    if move_to == department_id:
        raise invalid_fields({"department_id": [_("Choose another department.")]})
    people = list(working_in(branch_id, department_id).select_for_update(of=("self",))
                  .order_by("pk"))
    if people:
        _require_people(actor, branch_id)
    recording = Recording(actor, StructureChangeKind.REMOVE_DEPARTMENT, name=department.name,
                          place=_place_name(branch_id))
    recording.watch_people(people, day)
    recording.watch_placement(department_id, branch_id)
    for person in people:
        _place(person, branch_id, move_to, day, "", actor)
    remove_department_branch(department, branch_id)
    recording.save()
    return len(people)


@transaction.atomic
def add_department(department_id: int, branch_id: int, *, actor=None) -> None:
    """The department starts operating in another branch."""
    department = _department(department_id)
    _require_departments(actor, branch_id)
    recording = Recording(actor, StructureChangeKind.ADD_DEPARTMENT, name=department.name,
                          place=_place_name(branch_id))
    recording.watch_placement(department_id, branch_id)
    add_department_branch(department, branch_id)
    recording.save()
