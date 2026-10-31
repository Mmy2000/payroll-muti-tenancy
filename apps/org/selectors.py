"""The branches and departments screens choose from."""

from __future__ import annotations

from django.db.models import Count, Max, Q

from .models import Branch, Department, TenantProfile
from .permissions import DEPARTMENT_VIEW


def active_branches():
    return Branch.objects.filter(is_active=True)


def active_branch_count() -> int:
    return active_branches().count()


def all_branches():
    return Branch.objects.all()


def branches_by_code(allowed=None):
    """`allowed`: the branch ids a member may choose from, None for every branch."""
    branches = Branch.objects.order_by("code")
    return branches if allowed is None else branches.filter(pk__in=allowed)


def active_branches_by_code(allowed=None):
    return branches_by_code(allowed).filter(is_active=True)


def branches_with_department_counts():
    return Branch.objects.annotate(
        department_count=Count("departments", filter=Q(departments__is_active=True))
    ).order_by("code")


def branch_by_id(pk) -> Branch | None:
    return Branch.objects.filter(pk=pk).first()


def next_branch_code() -> int:
    return (Branch.objects.aggregate(top=Max("code"))["top"] or 0) + 1


def branch_departments(branch: Branch):
    return branch.departments.order_by("code")


def branch_choices(allowed):
    """The active branches, by code, of `allowed` (None = all of them)."""
    branches = active_branches().order_by("code")
    return branches if allowed is None else branches.filter(pk__in=allowed)


def visible_departments(actor=None, permission: str = DEPARTMENT_VIEW):
    """Departments, with their branch, in the branches where the member has `permission`."""
    departments = Department.objects.select_related("branch")
    allowed = actor.branch_ids(permission) if actor is not None else None
    return departments if allowed is None else departments.filter(branch_id__in=allowed)


def visible_department(actor, pk, permission: str = DEPARTMENT_VIEW) -> Department | None:
    return visible_departments(actor, permission).filter(pk=pk).first()


def next_department_code(branch_id: int) -> int:
    return (Department.objects.filter(branch_id=branch_id)
            .aggregate(top=Max("code"))["top"] or 0) + 1


def tenant_profile() -> TenantProfile:
    return TenantProfile.objects.get()


def tenant_profile_or_none() -> TenantProfile | None:
    return TenantProfile.objects.first()
