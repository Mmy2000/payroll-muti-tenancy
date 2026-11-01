from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.iam.authz import permission_required

from .. import permissions, selectors
from ..listing import ListQuery
from ..validators import branch_in_use, department_in_use


@permission_required("org.branch.view")
def branches(request):
    return render(request, "org/branches.html", {
        "branches": selectors.branches_with_department_counts(),
        "can_create": request.actor.holds_everywhere(permissions.BRANCH_MANAGE)})


def _with_can_edit(actor, departments) -> list:
    """Each department, saying whether this member may open its form."""
    for department in departments:
        department.can_edit = selectors.covers(actor, department, permissions.DEPARTMENT_MANAGE)
    return departments


def _branch_form(request, branch=None):
    next_code = selectors.next_branch_code()
    return render(request, "org/branch_form.html", {
        "branch": branch,
        "departments": (_with_can_edit(request.actor, list(selectors.branch_departments(branch)))
                        if branch else []),
        "in_use": branch is not None and branch_in_use(branch),
        "can_choose_head_office": request.actor.holds_everywhere(permissions.BRANCH_MANAGE),
        "next_code": next_code,
        "endpoint": (reverse("branch-detail", args=[branch.pk]) if branch
                     else reverse("branch-list")),
        "method": "PUT" if branch else "POST",
    })


@permission_required(permissions.BRANCH_MANAGE)
def branch_new(request):
    if not request.actor.holds_everywhere(permissions.BRANCH_MANAGE):
        raise PermissionDenied
    return _branch_form(request)


@permission_required(permissions.BRANCH_MANAGE)
def branch_edit(request, pk):
    branch = selectors.branch_by_id(pk)
    if branch is None or not request.actor.can(permissions.BRANCH_MANAGE, branch=branch):
        raise Http404
    return _branch_form(request, branch)


@permission_required(permissions.DEPARTMENT_VIEW)
def departments(request):
    found = ListQuery(request, permission=permissions.DEPARTMENT_VIEW, search=("name",),
                      search_label=_("Department name"), date_field="",
                      branch_field=selectors.in_branches)
    page = found.page(found.apply(selectors.visible_departments(request.actor)))
    _with_can_edit(request.actor, page.object_list)
    return render(request, "org/departments.html", {"filters": found, "page": page})


def _department_form(request, department=None):
    allowed = request.actor.branch_ids(permissions.DEPARTMENT_MANAGE)
    return render(request, "org/department_form.html", {
        "department": department,
        "in_use": department is not None and department_in_use(department),
        "branches": selectors.branches_for_department(allowed, department),
        "chosen_branches": (set(department.branch_ids) if department
                            else {int(pk) for pk in request.GET.getlist("branch") if pk.isdigit()}),
        "endpoint": (reverse("department-detail", args=[department.pk]) if department
                     else reverse("department-list")),
        "method": "PUT" if department else "POST",
    })


@permission_required(permissions.DEPARTMENT_MANAGE)
def department_new(request):
    return _department_form(request)


@permission_required(permissions.DEPARTMENT_MANAGE)
def department_edit(request, pk):
    department = selectors.visible_department(request.actor, pk, permissions.DEPARTMENT_MANAGE)
    if department is None or not selectors.covers(request.actor, department,
                                                  permissions.DEPARTMENT_MANAGE):
        raise Http404
    return _department_form(request, department)


@permission_required(permissions.POSITION_VIEW)
def positions(request):
    found = ListQuery(request, permission=permissions.POSITION_VIEW, search=("name",),
                      search_label=_("Position name"), date_field="", branch_field="")
    rows = found.apply(selectors.positions())
    return render(request, "org/positions.html", {"filters": found, "page": found.page(rows)})


def _position_form(request, position=None):
    return render(request, "org/position_form.html", {
        "position": position,
        "departments": selectors.active_departments(),
        "endpoint": (reverse("position-detail", args=[position.pk]) if position
                     else reverse("position-list")),
        "method": "PUT" if position else "POST",
    })


@permission_required(permissions.POSITION_MANAGE)
def position_new(request):
    return _position_form(request)


@permission_required(permissions.POSITION_MANAGE)
def position_edit(request, pk):
    position = selectors.find_position(pk)
    if position is None:
        raise Http404
    return _position_form(request, position)
