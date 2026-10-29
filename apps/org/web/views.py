from django.db.models import Max
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from apps.iam.authz import permission_required
from apps.org.models import Branch, Department


@permission_required("org.branch.view")
def branches(request):
    return render(request, "org/branches.html", {"branches": Branch.objects.order_by("code")})


def _branch_form(request, branch=None):
    next_code = (Branch.objects.aggregate(top=Max("code"))["top"] or 0) + 1
    return render(request, "org/branch_form.html", {
        "branch": branch,
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


@permission_required("org.department.view")
def departments(request):
    return render(request, "org/departments.html",
                  {"departments": Department.objects.order_by("code")})


def _department_form(request, department=None):
    next_code = (Department.objects.aggregate(top=Max("code"))["top"] or 0) + 1
    return render(request, "org/department_form.html", {
        "department": department,
        "next_code": next_code,
        "endpoint": (reverse("department-detail", args=[department.pk]) if department
                     else reverse("department-list")),
        "method": "PUT" if department else "POST",
    })


@permission_required("org.department.manage")
def department_new(request):
    return _department_form(request)


@permission_required("org.department.manage")
def department_edit(request, pk):
    department = Department.objects.filter(pk=pk).first()
    if department is None:
        raise Http404
    return _department_form(request, department)
