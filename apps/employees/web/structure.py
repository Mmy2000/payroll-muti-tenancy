"""The company structure page: the page itself. static/employees/js/structure/ draws the canvas
and the list from the API, so moving something never reloads the page."""

from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.iam.authz import permission_required
from apps.org.selectors import active_departments

from .. import selectors
from ..permissions import MANAGE, VIEW


def _words() -> dict:
    """What the script says, in the viewer's language."""
    return {
        "branch": _("Branch"), "department": _("Department"), "employee": _("Employee"),
        "no_department": _("No department"), "head_office": _("Head office"),
        "inactive": _("Inactive"), "employees": _("Employees"), "departments": _("Departments"),
        "branches": _("Branches"), "close": _("Close"), "show_more": _("Show more"),
        "code": _("Code"), "job": _("Job"), "also_in": _("Also in"), "only_here": _("Only here"),
        "open": _("Open the employee's page"), "edit": _("Edit"),
        "edit_branch": _("Edit the branch"), "edit_department": _("Edit the department"),
        "new_department": _("New department"), "new_employee": _("New employee"),
        "add_department": _("Add a department to this branch"),
        "move_department": _("Move to another branch"),
        "remove_department": _("Remove from this branch"),
        "move_employee": _("Move"), "move_selected": _("Move the selected"),
        "clear": _("Clear"), "selected": _("selected"),
        "loading": _("Loading…"), "nobody": _("Nobody here yet."),
        "nothing_found": _("Nothing matches your search."),
        "pick_something": _("Select a branch, a department or an employee to see what you can "
                            "do with them."),
        "title_move_people": _("Move employees"),
        "title_move_department": _("Move the department"),
        "title_remove_department": _("Remove the department from this branch"),
        "title_add_department": _("Add a department"),
        "people_go_along": _("Employees here who move with it:"),
        "people_stay": _("Employees here who need a new department:"),
        "last_branch": _("This is the department's only branch."),
        "saved": _("Saved."),
    }


@permission_required(VIEW)
def structure(request):
    actor = request.actor
    return render(request, "employees/structure.html", {
        "today": timezone.localdate(),
        "branches": selectors.branch_choices(actor, MANAGE),
        "departments": selectors.department_choices(actor, MANAGE),
        "all_departments": active_departments(),
        "config": {
            "words": _words(),
            "company": request.tenant.name,
            "api": {"tree": reverse("structure-list"), "people": reverse("structure-people"),
                    "search": reverse("structure-search"),
                    "move_people": reverse("structure-move-people"),
                    "move_department": reverse("structure-move-department"),
                    "add_department": reverse("structure-add-department"),
                    "remove_department": reverse("structure-remove-department")}},
    })
