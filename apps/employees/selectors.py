"""Which employees an actor may see, and who something is given to: one employee, a department
or a branch (PayRole's `ee` scope 1/2/3). `resolve()` turns a target into the employees it means
on a day: those the actor may act on, employed that day. A department or branch with nobody in it
is an error, so nothing is "given" to no one silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Max, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import NotFound, ValidationError
from apps.core.history import in_effect
from apps.iam.limits import is_app_login
from apps.org.selectors import branch_choices as active_branch_choices
from apps.org.selectors import visible_departments
from apps.policies.models import LatenessPolicy, OvertimePolicy

from .models import Employee
from .permissions import VIEW

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


def employed_on(day: date):
    return Q(hired_on__lte=day) & (Q(left_on__isnull=True) | Q(left_on__gte=day))


def resolve(target: Target, *, on: date, actor=None, permission: str) -> list[Employee]:
    if target.kind not in KINDS:
        raise ValidationError(_("Choose who this is for."),
                              fields={"target_kind": [_("Choose who this is for.")]})
    field = {EMPLOYEE: "pk", DEPARTMENT: "department_id", BRANCH: "branch_id"}[target.kind]
    people = list(visible_employees(actor, permission).filter(employed_on(on), **{field: target.id})
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
            return resolve(Target(group.kind, group.id or 0), on=on, actor=actor,
                           permission=permission)
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


def department_in_use(department) -> bool:
    return Employee.objects.filter(department=department).exists()
