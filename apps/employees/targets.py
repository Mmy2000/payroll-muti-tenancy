"""Who something is given to: one employee, a department or a branch (PayRole's `ee` scope 1/2/3,
expanded there by every screen on its own). Incentives, penalties and pay items all use this.

`resolve()` turns a target into the employees it means on a day: those the actor may act on
(the permission's branches), employed that day. A department or branch with nobody in it is an
error, so nothing is "given" to no one silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.errors import ValidationError

from .models import Employee
from .services import visible_employees

EMPLOYEE, DEPARTMENT, BRANCH = "employee", "department", "branch"
KINDS = (EMPLOYEE, DEPARTMENT, BRANCH)


@dataclass(frozen=True)
class Target:
    kind: str
    id: int  # the employee, department or branch

    @classmethod
    def employee(cls, employee_id: int) -> Target:
        return cls(EMPLOYEE, employee_id)


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
