"""The choices for a "who it's for" picker (templates: employees/_target_fields.html)."""

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.employees.services import visible_employees
from apps.employees.targets import BRANCH, DEPARTMENT, EMPLOYEE, EMPLOYEES
from apps.org.models import Branch, Department

KINDS = [(EMPLOYEE, _("One employee")), (DEPARTMENT, _("A department")),
         (BRANCH, _("A branch"))]


def employee_choices(actor, permission: str):
    """Employees still working whom the member may act on with `permission`."""
    return visible_employees(actor, permission).exclude(
        left_on__lt=timezone.localdate()).order_by("code")


GROUP_KINDS = [(EMPLOYEES, _("Chosen employees")), (DEPARTMENT, _("A department")),
               (BRANCH, _("A branch"))]


def group_choices(actor, permission: str) -> dict:
    """The choices of a group picker (employees/_group_fields.html)."""
    choices = target_choices(actor, permission)
    return {"group_kinds": GROUP_KINDS, "group_employees": choices["target_employees"],
            "group_departments": choices["target_departments"],
            "group_branches": choices["target_branches"]}


def group_page(request, permission: str, **page) -> dict:
    """The context of a bulk-change page (layouts/bulk_form.html): the group picker's choices,
    today, and the page's words and addresses."""
    return {**group_choices(request.actor, permission), "today": timezone.localdate(), **page}


def target_choices(actor, permission: str) -> dict:
    """Employees still working, departments and branches the member may give things to."""
    allowed = actor.branch_ids(permission)
    branches = Branch.objects.filter(is_active=True).order_by("code")
    return {
        "target_kinds": KINDS,
        "target_employees": employee_choices(actor, permission),
        "target_departments": Department.objects.filter(is_active=True).order_by("code"),
        "target_branches": branches if allowed is None else branches.filter(pk__in=allowed),
    }
