"""The branches and departments screens choose from."""

from __future__ import annotations

from django.db.models import Count, Max, Q

from .models import Branch, Department, Position, TenantProfile
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
    departments = Department.objects.prefetch_related("placements__branch")
    allowed = actor.branch_ids(permission) if actor is not None else None
    if allowed is None:
        return departments
    return departments.filter(placements__branch_id__in=allowed).distinct()


def in_branches(departments, branch_ids):
    return departments.filter(placements__branch_id__in=branch_ids).distinct()


def covers(actor, department: Department, permission: str) -> bool:
    """A change to a department touches all its branches, so it takes all of them."""
    allowed = actor.branch_ids(permission)
    return allowed is None or set(department.branch_ids) <= allowed


def branches_for_department(allowed, department: Department | None):
    """The branches its form offers: the active ones the member may use, and those it is in."""
    current = department.branch_ids if department is not None else []
    choices = Branch.objects.filter(is_active=True)
    if allowed is not None:
        choices = choices.filter(pk__in=allowed)
    return (choices | Branch.objects.filter(pk__in=current)).distinct().order_by("code")


def visible_department(actor, pk, permission: str = DEPARTMENT_VIEW) -> Department | None:
    return visible_departments(actor, permission).filter(pk=pk).first()


def active_departments():
    return visible_departments().filter(is_active=True)


def next_department_code() -> int:
    return (Department.objects.aggregate(top=Max("code"))["top"] or 0) + 1


def tenant_profile() -> TenantProfile:
    return TenantProfile.objects.get()


def tenant_profile_or_none() -> TenantProfile | None:
    return TenantProfile.objects.first()


def positions():
    return Position.objects.select_related("department").order_by("name")


def active_positions():
    return positions().filter(is_active=True)


def find_position(pk: int) -> Position | None:
    return positions().filter(pk=pk).first()
