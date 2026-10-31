"""The rules on a department."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

from .models import Branch, Department, Position

if TYPE_CHECKING:
    from .services import DepartmentInput, PositionInput


_department_checks = []
_branch_checks = []


def register_use(*, department, branch) -> None:
    """For an app whose records point at departments and branches: `department(row, branch_ids)`
    (any of those branches, or all when None) and `branch(row)` say whether any do."""
    _department_checks.append(department)
    _branch_checks.append(branch)


def department_in_use(department: Department, branch_ids=None) -> bool:
    return any(check(department, branch_ids) for check in _department_checks)


def branch_in_use(branch: Branch) -> bool:
    return any(check(branch) for check in _branch_checks)


def check_department(department: Department, data: DepartmentInput) -> dict:
    """Code and name are the company's. A branch where employees work in the department stays:
    their department must be in their own branch."""
    errors: dict[str, list[str]] = {}
    others = Department.objects.exclude(pk=department.pk)
    current = set(department.branch_ids) if department.pk else set()
    wanted = set(data.branch_ids)
    added, removed = wanted - current, current - wanted
    if not wanted:
        errors["branches"] = [_("Choose at least one branch.")]
    elif Branch.objects.filter(pk__in=added, is_active=True).count() != len(added):
        errors["branches"] = [_("Choose active branches.")]
    elif removed and department_in_use(department, removed):
        errors["branches"] = [_("Employees work there in this department: move them first.")]
    if data.code is not None and others.filter(code=data.code).exists():
        errors["code"] = [_("Another department has this code.")]
    if others.filter(name=data.name.strip()).exists():
        errors["name"] = [_("Another department has this name.")]
    return errors


def check_position(position: Position, data: PositionInput) -> dict:
    errors: dict[str, list[str]] = {}
    name = data.name.strip()
    if not name:
        errors["name"] = [_("Enter a name.")]
    elif Position.objects.filter(name=name).exclude(pk=position.pk).exists():
        errors["name"] = [_("Another position has this name.")]
    if (data.department_id is not None and data.department_id != position.department_id
            and not Department.objects.filter(pk=data.department_id, is_active=True).exists()):
        errors["department"] = [_("Choose an active department.")]
    return errors
