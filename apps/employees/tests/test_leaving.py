"""Leaving ends access, and a deactivated branch or department doesn't freeze anyone's card."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.errors import PermissionDenied
from apps.core.tenancy import tenant_context
from apps.employees.models import Employee
from apps.employees.services import employees
from apps.iam.authz import build_actor
from apps.iam.models import Membership, MembershipStatus
from apps.mobile.services import access
from apps.mobile.tests.test_contract import App, _switch
from apps.org import services as org
from apps.org.models import Branch
from apps.platform.tenants.models import Tenant
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db


def _yesterday():
    return timezone.localdate() - timedelta(days=1)


def _status(member) -> str:
    return Membership.objects.get(pk=member.pk).status


def _card(person, **changes):
    values = {"code": person.code, "name": person.name, "branch_id": person.branch_id,
              "hired_on": person.hired_on, "department_id": person.department_id}
    return employees.EmployeeInput(**{**values, **changes})


@pytest.fixture
def linked(tenant_a, make_member, make_employee):
    person = make_employee(tenant_a, 7)
    member = make_member(tenant_a, "leaver", "manager")
    with tenant_context(tenant_a.id):
        Employee.objects.filter(pk=person.pk).update(member=member)
    return person, member


def test_leaving_suspends_the_login(tenant_a, linked):
    person, member = linked
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, _yesterday())
        assert _status(member) == MembershipStatus.SUSPENDED


def test_a_departure_ahead_waits_for_the_day(tenant_a, linked):
    person, member = linked
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, timezone.localdate())
        assert _status(member) == MembershipStatus.ACTIVE
        assert employees.close_leavers_logins() == 0
        Employee.objects.filter(pk=person.pk).update(left_on=_yesterday())
        assert employees.close_leavers_logins() == 1
        assert _status(member) == MembershipStatus.SUSPENDED


def test_the_app_login_of_a_leaver_stops_and_frees_its_place(tenant_a, make_employee):
    _switch(tenant_a)
    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id):
        access.give_login(person.pk, "gone", PASSWORD)
        employees.end_employment(person.pk, _yesterday())
    assert App(tenant_a).sign_in("gone").status_code == 401


def test_the_last_owner_keeps_their_login(tenant_a, make_employee):
    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id):
        owner = Membership.objects.get(username="owner")
        Employee.objects.filter(pk=person.pk).update(member=owner)
        employees.end_employment(person.pk, _yesterday())
        assert _status(owner) == MembershipStatus.ACTIVE
    assert login(tenant_a).get("/api/web/employees/employees/").status_code == 200


def test_reinstating_opens_the_login_only_when_asked(tenant_a, linked):
    person, member = linked
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, _yesterday())
        employees.reinstate(person.pk)
        assert _status(member) == MembershipStatus.SUSPENDED
        employees.end_employment(person.pk, _yesterday())
        employees.reinstate(person.pk, restore_login=True)
        assert _status(member) == MembershipStatus.ACTIVE


def test_opening_a_login_needs_the_right_to_manage_users(tenant_a, linked, make_member):
    person, member = linked
    hr = make_member(tenant_a, "hr", "manager")
    with tenant_context(tenant_a.id):
        employees.end_employment(person.pk, _yesterday())
        with pytest.raises(PermissionDenied):
            employees.reinstate(person.pk, restore_login=True,
                                actor=build_actor(Membership.objects.get(pk=hr.pk)))
        assert Employee.objects.get(pk=person.pk).left_on is not None  # nothing half done


def test_a_card_can_be_saved_in_a_deactivated_department_and_branch(tenant_a, make_employee):
    with tenant_context(tenant_a.id):
        branch = org.create_branch(org.BranchInput(code=2, name="B"))
        department = org.save_department(org.DepartmentInput(name="Sales", branch_ids=(branch.pk,)))
    person = make_employee(tenant_a, 7, branch=branch, department_id=department.pk)
    with tenant_context(tenant_a.id):
        org.set_department_active(department.pk, False)
        org.set_branch_active(branch.pk, False)
        employees.update_employee(person.pk, _card(person, name="Renamed"))
        assert Employee.objects.get(pk=person.pk).name == "Renamed"


def test_nobody_is_moved_into_something_deactivated(tenant_a, make_employee):
    from apps.core.errors import ValidationError

    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id):
        branch = org.create_branch(org.BranchInput(code=2, name="B"))
        org.set_branch_active(branch.pk, False)
        with pytest.raises(ValidationError) as refused:
            employees.update_employee(person.pk, _card(person, branch_id=branch.pk))
        assert "branch_id" in refused.value.fields


def test_reactivating_a_branch_respects_the_plans_limit(tenant_a):
    from apps.core.errors import DomainError

    Tenant.objects.filter(pk=tenant_a.pk).update(max_branches=2)
    with tenant_context(tenant_a.id):
        second = org.create_branch(org.BranchInput(code=2, name="B"))
        org.set_branch_active(second.pk, False)
        org.create_branch(org.BranchInput(code=3, name="C"))
        with pytest.raises(DomainError):
            org.set_branch_active(second.pk, True)
        assert Branch.objects.filter(is_active=True).count() == 2


def test_the_pages_warn_before_deactivating_what_is_in_use(tenant_a, make_employee):
    with tenant_context(tenant_a.id):
        branch = org.create_branch(org.BranchInput(code=2, name="B"))
    make_employee(tenant_a, 7, branch=branch)
    page = login(tenant_a, language="en").get(f"/branches/{branch.pk}/").content.decode()
    assert "Employees work in this branch" in page
