"""The branches and departments screens choose from."""

from __future__ import annotations

from django.db.models import Max

from .models import Branch, Department
from .permissions import DEPARTMENT_VIEW


def active_branches():
    return Branch.objects.filter(is_active=True)


def visible_departments(actor=None, permission: str = DEPARTMENT_VIEW):
    """Departments, with their branch, in the branches where the member has `permission`."""
    departments = Department.objects.select_related("branch")
    allowed = actor.branch_ids(permission) if actor is not None else None
    return departments if allowed is None else departments.filter(branch_id__in=allowed)


def next_department_code(branch_id: int) -> int:
    return (Department.objects.filter(branch_id=branch_id)
            .aggregate(top=Max("code"))["top"] or 0) + 1
