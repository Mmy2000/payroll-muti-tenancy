from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.iam.authz import permission_required

from .. import permissions, selectors
from ..listing import ListQuery


@permission_required("org.branch.view")
def branches(request):
    return render(request, "org/branches.html",
                  {"branches": selectors.branches_with_department_counts()})


def _branch_form(request, branch=None):
    next_code = selectors.next_branch_code()
    return render(request, "org/branch_form.html", {
        "branch": branch,
        "departments": selectors.branch_departments(branch) if branch else [],
        "next_code": next_code,
        "endpoint": (reverse("branch-detail", args=[branch.pk]) if branch
                     else reverse("branch-list")),
        "method": "PUT" if branch else "POST",
    })


@permission_required("org.branch.manage")
def branch_new(request):
    return _branch_form(request)


@permission_required("org.branch.manage")
def branch_edit(request, pk):
    branch = selectors.branch_by_id(pk)
    if branch is None:
        raise Http404
    return _branch_form(request, branch)


@permission_required(permissions.DEPARTMENT_VIEW)
def departments(request):
    found = ListQuery(request, permission=permissions.DEPARTMENT_VIEW, search=("name",),
                      search_label=_("Department name"), date_field="")
    rows = found.apply(selectors.visible_departments(request.actor))
    return render(request, "org/departments.html", {"filters": found, "page": found.page(rows)})


def _department_form(request, department=None):
    allowed = request.actor.branch_ids(permissions.DEPARTMENT_MANAGE)
    return render(request, "org/department_form.html", {
        "department": department,
        "branches": selectors.active_branches_by_code(allowed),
        "chosen_branch": department.branch_id if department else request.GET.get("branch", ""),
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
    if department is None:
        raise Http404
    return _department_form(request, department)
