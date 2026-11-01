"""Which employees an actor may see, and who something is given to: one employee, a department
or a branch (PayRole's `ee` scope 1/2/3). `resolve()` turns a target into the employees it means
on a day: those the actor may act on, employed that day. A department or branch with nobody in it
is an error, so nothing is "given" to no one silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, ValidationError
from apps.core.history import in_effect
from apps.iam.limits import is_app_login
from apps.org.models import Branch, DepartmentBranch
from apps.org.permissions import DEPARTMENT_MANAGE
from apps.org.selectors import branch_choices as active_branch_choices
from apps.org.selectors import visible_departments
from apps.policies.models import LatenessPolicy, OvertimePolicy

from .models import Employee
from .permissions import MANAGE, VIEW

EMPLOYEE, DEPARTMENT, BRANCH = "employee", "department", "branch"
KINDS = (EMPLOYEE, DEPARTMENT, BRANCH)
EMPLOYEES = "employees"
GROUP_KINDS = (EMPLOYEES, DEPARTMENT, BRANCH)


def visible_employees(actor, code: str = VIEW):
    """Employees of the branches where `actor` holds `code` (all of them for a trusted caller)."""
    employees = Employee.objects.all()
    if actor is None:
        return employees
    branches = actor.branch_ids(code)
    return employees if branches is None else employees.filter(branch_id__in=branches)


def listed_employees(actor, code: str = VIEW):
    """The employees of a list: with their branch and department, by code."""
    return visible_employees(actor, code).select_related("branch", "department").order_by("code")


def by_status(employees, value: str):
    today = timezone.localdate()
    if value == "active":
        return employees.exclude(left_on__lt=today)
    if value == "left":
        return employees.filter(left_on__lt=today)
    return employees


def employee_choices(actor, permission: str):
    """Employees still working whom the member may act on with `permission`."""
    return visible_employees(actor, permission).exclude(
        left_on__lt=timezone.localdate()).order_by("code")


def branch_choices(actor, permission: str):
    """Active branches where the member holds `permission`."""
    return active_branch_choices(actor.branch_ids(permission))


def department_choices(actor, permission: str):
    """Active departments in the branches where the member holds `permission`."""
    return visible_departments(actor, permission).filter(is_active=True)


def active_lateness_policies():
    return LatenessPolicy.objects.filter(is_active=True)


def active_overtime_policies():
    return OvertimePolicy.objects.filter(is_active=True)


def all_rows(model):
    return model.objects.all()


def employee_rows(rows, actor, code: str, related=("employee",)):
    """Those of `rows` that belong to employees the member may see under `code`."""
    return rows.filter(employee__in=visible_employees(actor, code)).select_related(*related)


def schedule_history(employee: Employee):
    return (employee.schedules.select_related("lateness_policy", "overtime_policy")
            .order_by("-effective_from", "-id"))


def schedule_on(employee: Employee, day: date):
    return in_effect(employee.schedules.all(), day)


def assignment_history(employee: Employee):
    return (employee.assignments.select_related("branch", "department", "position")
            .order_by("-effective_from", "-id"))


def assignment_on(employee: Employee, day: date):
    return in_effect(employee.assignments.all(), day)


def pay_history(employee: Employee):
    return employee.pay_history.order_by("-effective_from", "-id")


def office_member(employee: Employee):
    """The user linked to `employee` if they also work in the office, not a login made for the
    app only."""
    if not employee.member_id or is_app_login(
            employee.member.roles.values_list("role__code", flat=True)):
        return None
    return employee.member


def get_employee(employee_id: int, actor=None, code: str = VIEW, *, lock=False) -> Employee:
    employees = visible_employees(actor, code)
    if lock:
        employees = employees.select_for_update(of=("self",))
    employee = employees.filter(pk=employee_id).first()
    if employee is None:
        raise NotFound(_("Not found."))
    return employee


def next_code() -> int:
    return (Employee.objects.aggregate(top=Max("code"))["top"] or 0) + 1


@dataclass(frozen=True)
class Target:
    kind: str
    id: int  # the employee, department or branch
    branch_id: int | None = None  # a department in this branch only; None: in all of them

    @classmethod
    def employee(cls, employee_id: int) -> Target:
        return cls(EMPLOYEE, employee_id)


@dataclass(frozen=True)
class Group:
    """Several employees at once (the bulk changes, apps/core/bulk.py): chosen one by one
    (`employee_ids`), or everyone of a department or a branch (`id`)."""

    kind: str
    employee_ids: tuple[int, ...] = ()
    id: int | None = None
    branch_id: int | None = None  # a department in this branch only; None: in all of them


def employed_on(day: date):
    return Q(hired_on__lte=day) & (Q(left_on__isnull=True) | Q(left_on__gte=day))


def resolve(target: Target, *, on: date, actor=None, permission: str) -> list[Employee]:
    if target.kind not in KINDS:
        raise ValidationError(_("Choose who this is for."),
                              fields={"target_kind": [_("Choose who this is for.")]})
    field = {EMPLOYEE: "pk", DEPARTMENT: "department_id", BRANCH: "branch_id"}[target.kind]
    chosen = {field: target.id}
    if target.kind == DEPARTMENT and target.branch_id is not None:
        chosen["branch_id"] = target.branch_id
    people = list(visible_employees(actor, permission).filter(employed_on(on), **chosen)
                  .select_for_update(of=("self",)).order_by("pk"))
    if not people:
        message = (_("This employee isn't employed on that day, or isn't yours to manage.")
                   if target.kind == EMPLOYEE
                   else _("Nobody you manage there is employed on that day."))
        raise ValidationError(message, fields={"target_id": [message]})
    return people


def resolve_group(group: Group, *, on: date, actor=None, permission: str) -> list[Employee]:
    """The employees of a group, locked, in a stable order. Chosen employees are all kept, so
    one not employed on the day gets a row that says so; a department or branch means those
    employed on the day. Someone the actor may not act on is refused outright."""
    if group.kind not in GROUP_KINDS:
        raise ValidationError(_("Choose who this is for."),
                              fields={"group_kind": [_("Choose who this is for.")]})
    if group.kind != EMPLOYEES:
        try:
            return resolve(Target(group.kind, group.id or 0, group.branch_id), on=on,
                           actor=actor, permission=permission)
        except ValidationError as error:
            raise ValidationError(error.message, fields={"group_id": [error.message]}) from None
    ids = set(group.employee_ids)
    if not ids:
        raise ValidationError(_("Choose at least one employee."),
                              fields={"employee_ids": [_("Choose at least one employee.")]})
    people = list(visible_employees(actor, permission).filter(pk__in=ids)
                  .select_for_update(of=("self",)).order_by("code", "pk"))
    if len(people) != len(ids):
        message = _("Some of these employees aren't yours to manage.")
        raise ValidationError(message, fields={"employee_ids": [message]})
    return people


def department_has_employees(department, branch_ids=None) -> bool:
    """Whether anyone still working is in it. Someone who left keeps it on their record."""
    people = Employee.objects.filter(department=department).exclude(
        left_on__lt=timezone.localdate())
    return (people if branch_ids is None else people.filter(branch_id__in=branch_ids)).exists()


def has_employees(branch) -> bool:
    return Employee.objects.filter(branch=branch).exists()


# --- the company structure page ---------------------------------------------------------------


def working_in(branch_id: int, department_id: int | None):
    """Who works in this branch and department now (None: in no department)."""
    return Employee.objects.filter(branch_id=branch_id, department_id=department_id).exclude(
        left_on__lt=timezone.localdate())


def _head_counts(actor) -> dict:
    rows = visible_employees(actor).exclude(left_on__lt=timezone.localdate()).values(
        "branch_id", "department_id").annotate(people=Count("pk")).order_by()
    return {(row["branch_id"], row["department_id"]): row["people"] for row in rows}


def _department_node(placement, counts, can_edit_url: bool) -> dict:
    department = placement.department
    return {"id": department.pk, "code": department.code, "name": department.name,
            "is_active": department.is_active,
            "people": counts.get((placement.branch_id, department.pk), 0),
            "edit_url": reverse("department-edit", args=[department.pk]) if can_edit_url else ""}


def structure_tree(actor) -> dict:
    """The branches the member sees, each with its departments and how many people are in them.
    The people themselves come when a node is opened: a company can have thousands."""
    allowed = actor.branch_ids(VIEW)
    branches = Branch.objects.order_by("code")
    branches = branches if allowed is None else branches.filter(pk__in=allowed)
    placements = DepartmentBranch.objects.select_related("department").order_by("department__code")
    counts = _head_counts(actor)
    in_branch: dict[int, list] = {}
    every_branch: dict[int, list] = {}
    for placement in placements:
        in_branch.setdefault(placement.branch_id, []).append(placement)
        every_branch.setdefault(placement.department_id, []).append(placement.branch_id)
    nodes = []
    for branch in branches:
        can_structure = actor.can(DEPARTMENT_MANAGE, branch=branch.pk)
        departments = [
            {**_department_node(row, counts, can_structure),
             "branch_ids": every_branch[row.department_id]}
            for row in in_branch.get(branch.pk, [])]
        nodes.append({
            "id": branch.pk, "code": branch.code, "name": branch.name,
            "is_active": branch.is_active, "is_head_office": branch.is_head_office,
            "people": sum(n for (place, _d), n in counts.items() if place == branch.pk),
            "unassigned": counts.get((branch.pk, None), 0), "departments": departments,
            "can_manage_people": actor.can(MANAGE, branch=branch.pk),
            "can_manage_departments": can_structure,
            "edit_url": (reverse("branch-edit", args=[branch.pk])
                         if actor.can("org.branch.manage", branch=branch.pk) else "")})
    return {"branches": nodes, "can_add_department": actor.holds_everywhere(DEPARTMENT_MANAGE),
            "can_add_employee": actor.can("employees.salary.manage"),
            "urls": {"new_department": reverse("department-new"),
                     "new_employee": reverse("employee-new")}}


def _person(employee: Employee) -> dict:
    return {"id": employee.pk, "code": employee.code, "name": employee.name,
            "job_title": employee.job_title, "branch_id": employee.branch_id,
            "department_id": employee.department_id,
            "url": reverse("employee", args=[employee.pk])}


def structure_people(actor, branch_id: int | None, department_id: int | None) -> list[dict]:
    if branch_id is None:
        return []
    return [_person(employee) for employee in (
        visible_employees(actor).filter(branch_id=branch_id, department_id=department_id)
        .exclude(left_on__lt=timezone.localdate()).order_by("name"))]


def structure_search(actor, text: str, *, limit: int = 30) -> list[dict]:
    """Working employees by name, code or job, to find them in the tree."""
    if not text:
        return []
    match = Q(name__icontains=text) | Q(job_title__icontains=text)
    if text.isdigit():
        match |= Q(code=int(text))
    return [_person(employee) for employee in (
        visible_employees(actor).filter(match).exclude(left_on__lt=timezone.localdate())
        .order_by("name")[:limit])]
