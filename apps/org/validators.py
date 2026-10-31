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
    """For an app whose records point at departments and branches: `department(row)` and
    `branch(row)` say whether any do."""
    _department_checks.append(department)
    _branch_checks.append(branch)


def department_in_use(department: Department) -> bool:
    return any(check(department) for check in _department_checks)


def branch_in_use(branch: Branch) -> bool:
    return any(check(branch) for check in _branch_checks)


def check_department(department: Department, data: DepartmentInput) -> dict:
    """Code and name are unique within a branch. A department with employees stays in its
    branch: their department must be in their own branch."""
    errors: dict[str, list[str]] = {}
    neighbours = Department.objects.filter(branch_id=data.branch_id).exclude(pk=department.pk)
    if not Branch.objects.filter(pk=data.branch_id, is_active=True).exists():
        errors["branch"] = [_("Choose an active branch.")]
    elif (department.pk and department.branch_id != data.branch_id
          and department_in_use(department)):
        errors["branch"] = [_("This department has employees: move them first.")]
    if data.code is not None and neighbours.filter(code=data.code).exists():
        errors["code"] = [_("Another department in this branch has this code.")]
    if neighbours.filter(name=data.name.strip()).exists():
        errors["name"] = [_("Another department in this branch has this name.")]
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
