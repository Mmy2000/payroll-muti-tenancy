"""The rules on a department."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

from .models import Branch, Department

if TYPE_CHECKING:
    from .services import DepartmentInput


_in_use_checks = []


def register_department_use(check) -> None:
    """For an app whose records point at a department: `check(department)` says if any do."""
    _in_use_checks.append(check)


def check_department(department: Department, data: DepartmentInput) -> dict:
    """Code and name are unique within a branch. A department with employees stays in its
    branch: their department must be in their own branch."""
    errors: dict[str, list[str]] = {}
    neighbours = Department.objects.filter(branch_id=data.branch_id).exclude(pk=department.pk)
    if not Branch.objects.filter(pk=data.branch_id, is_active=True).exists():
        errors["branch"] = [_("Choose an active branch.")]
    elif (department.pk and department.branch_id != data.branch_id
          and any(check(department) for check in _in_use_checks)):
        errors["branch"] = [_("This department has employees: move them first.")]
    if data.code is not None and neighbours.filter(code=data.code).exists():
        errors["code"] = [_("Another department in this branch has this code.")]
    if neighbours.filter(name=data.name.strip()).exists():
        errors["name"] = [_("Another department in this branch has this name.")]
    return errors
