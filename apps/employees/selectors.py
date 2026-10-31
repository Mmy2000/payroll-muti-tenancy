"""Which employees an actor may see, and reading one."""

from __future__ import annotations

from django.db.models import Max
from django.utils.translation import gettext as _

from apps.core.errors import NotFound

from .models import Employee
from .permissions import VIEW


def visible_employees(actor, code: str = VIEW):
    """Employees of the branches where `actor` holds `code` (all of them for a trusted caller)."""
    employees = Employee.objects.all()
    if actor is None:
        return employees
    branches = actor.branch_ids(code)
    return employees if branches is None else employees.filter(branch_id__in=branches)


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
