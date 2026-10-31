from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.listing import ListQuery
from apps.iam.authz import permission_required
from apps.org.models import Branch

from .. import permissions, selectors


@permission_required("org.branch.view")
def branches(request):
    return render(request, "org/branches.html", {"branches": Branch.objects.annotate(
        department_count=Count("departments", filter=Q(departments__is_active=True)))
        .order_by("code")})


def _branch_form(request, branch=None):
    next_code = (Branch.objects.aggregate(top=Max("code"))["top"] or 0) + 1
    return render(request, "org/branch_form.html", {
        "branch": branch,
        "departments": branch.departments.order_by("code") if branch else [],
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
    branch = Branch.objects.filter(pk=pk).first()
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
    branches = Branch.objects.filter(is_active=True).order_by("code")
    if allowed is not None:
        branches = branches.filter(pk__in=allowed)
    return render(request, "org/department_form.html", {
        "department": department,
        "branches": branches,
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
    department = selectors.visible_departments(request.actor, permissions.DEPARTMENT_MANAGE).filter(
        pk=pk).first()
    if department is None:
        raise Http404
    return _department_form(request, department)
