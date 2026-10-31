"""A department has one code and one name, and operates in several branches. Each branch has its
own employees in it: an employee's department must be in their branch."""

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.errors import PermissionDenied, ValidationError
from apps.core.tenancy import tenant_context
from apps.employees.models import Employee
from apps.employees.selectors import DEPARTMENT, Group, Target, resolve, resolve_group
from apps.iam.authz import build_actor
from apps.iam.models import Membership
from apps.org import services
from apps.org.models import Branch, Department
from conftest import login

from .. import selectors

pytestmark = pytest.mark.django_db
EMPLOYEES = "employees.employee.manage"


@pytest.fixture
def branches(tenant_a):
    with tenant_context(tenant_a.id):
        return Branch.objects.get(code=1), Branch.objects.create(code=2, name="Alexandria")


def _save(name, *where, code=None, **kwargs):
    return services.save_department(
        services.DepartmentInput(branch_ids=tuple(b.pk for b in where), code=code, name=name),
        **kwargs)


def _actor(member):
    return build_actor(Membership.objects.get(pk=member.pk))


def test_one_department_with_one_code_in_several_branches(tenant_a, branches):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head, alexandria)
        accounts = _save("Accounts", head)
        assert (sales.code, accounts.code) == (1, 2)
        assert Department.objects.count() == 2
        assert set(sales.branch_ids) == {head.pk, alexandria.pk}
        assert set(head.departments.all()) == {sales, accounts}
        assert list(alexandria.departments.all()) == [sales]


def test_code_and_name_are_the_companys(tenant_a, branches):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        _save("Sales", head)
        with pytest.raises(ValidationError) as same_name:
            _save("Sales", alexandria)
        assert "name" in same_name.value.fields
        with pytest.raises(ValidationError) as same_code:
            _save("Stores", alexandria, code=1)
        assert "code" in same_code.value.fields


def test_each_branch_has_its_own_people(tenant_a, branches, make_employee):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head, alexandria)
    here = make_employee(tenant_a, 1, branch=head, department_id=sales.pk)
    there = make_employee(tenant_a, 2, branch=alexandria, department_id=sales.pk)
    day = timezone.localdate()
    with tenant_context(tenant_a.id):
        only_here = resolve(Target(DEPARTMENT, sales.pk, head.pk), on=day, permission=EMPLOYEES)
        assert [person.pk for person in only_here] == [here.pk]
        everyone = resolve(Target(DEPARTMENT, sales.pk), on=day, permission=EMPLOYEES)
        assert {person.pk for person in everyone} == {here.pk, there.pk}
        group = resolve_group(Group(DEPARTMENT, id=sales.pk, branch_id=alexandria.pk), on=day,
                              permission=EMPLOYEES)
        assert [person.pk for person in group] == [there.pk]


def test_an_employees_department_is_in_their_branch(tenant_a, branches, make_employee):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        there = _save("Sales", alexandria)
        with pytest.raises(ValidationError):
            make_employee(tenant_a, 1, branch=head, department_id=there.pk)
    person = make_employee(tenant_a, 2, branch=alexandria, department_id=there.pk)
    with tenant_context(tenant_a.id):
        assert Employee.objects.get(pk=person.pk).department_id == there.pk


def test_a_branch_can_be_added_and_left_if_nobody_works_there(tenant_a, branches, make_employee):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head)
    make_employee(tenant_a, 1, branch=head, department_id=sales.pk)
    with tenant_context(tenant_a.id):
        grown = _save_existing(sales, head, alexandria)
        assert set(Department.objects.get(pk=grown.pk).branch_ids) == {head.pk, alexandria.pk}
        _save_existing(sales, head)
        assert Department.objects.get(pk=sales.pk).branch_ids == [head.pk]
        with pytest.raises(ValidationError) as refused:
            _save_existing(sales, alexandria)
        assert "branches" in refused.value.fields


def _save_existing(department, *where):
    return services.save_department(
        services.DepartmentInput(name=department.name, branch_ids=tuple(b.pk for b in where)),
        department_id=department.pk)


def test_a_department_needs_a_branch(tenant_a, branches):
    with tenant_context(tenant_a.id), pytest.raises(ValidationError) as refused:
        _save("Sales")
    assert "branches" in refused.value.fields


def test_a_branch_manager_sees_theirs_and_changes_what_they_fully_cover(tenant_a, branches,
                                                                        make_member):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        shared = _save("Sales", head, alexandria)
        own = _save("Accounts", head)
        far = _save("Warehouse", alexandria)
    member = make_member(tenant_a, "local", "manager", branches=[head])
    with tenant_context(tenant_a.id):
        actor = _actor(member)
        seen = set(selectors.visible_departments(actor))
        assert seen == {shared, own}
        assert far not in seen
        _save("Stores", head, actor=actor)
        with pytest.raises(PermissionDenied):
            _save("Stores 2", alexandria, actor=actor)
        with pytest.raises(PermissionDenied):
            services.save_department(services.DepartmentInput("Renamed", (head.pk,)),
                                     department_id=shared.pk, actor=actor)
        with pytest.raises(PermissionDenied):
            services.set_department_active(shared.pk, False, actor=actor)
        services.set_department_active(own.pk, False, actor=actor)


def test_the_pages_show_a_department_and_its_branches(tenant_a, branches):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        _save("Sales", head, alexandria)
        _save("Accounts", head)
    client = login(tenant_a, language="en")
    made = client.post(reverse("department-list"),
                       {"branches": [head.pk, alexandria.pk], "name": "Stores", "code": None},
                       content_type="application/json")
    assert made.status_code == 201
    assert made.json()["branch_names"] == [head.name, "Alexandria"]
    page = client.get(reverse("departments")).content.decode()
    assert "Alexandria" in page and "Stores" in page
    filtered = client.get(f"{reverse('departments')}?branch={alexandria.pk}").content.decode()
    assert "Sales" in filtered and "Accounts" not in filtered
    form = client.get(f"{reverse('department-new')}?branch={alexandria.pk}").content.decode()
    assert f'<option value="{alexandria.pk}" selected>' in form


def test_a_picker_offers_a_department_under_each_of_its_branches(tenant_a, branches):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head, alexandria)
    page = login(tenant_a, language="en").get(reverse("employee-new")).content.decode()
    parents = {head.pk, alexandria.pk}
    assert f'data-parent="{" ".join(map(str, sorted(parents)))}"' in page, sales


def test_the_employee_import_finds_the_department_in_the_rows_branch(tenant_a, branches):
    from apps.employees.imports import EmployeeImport

    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head, alexandria)
        job = EmployeeImport(actor=None)
        job.prepare()
        assert job.departments[head.pk][sales.code] == sales.pk
        assert job.departments[alexandria.pk][sales.code] == sales.pk


def test_a_department_run_can_be_for_one_branch(tenant_a, branches, make_employee, make_member):
    from apps.payroll.services import runs
    from apps.platform.tenants import features
    from apps.platform.tenants.models import TenantFeature

    TenantFeature.objects.create(tenant=tenant_a, key="attendance", enabled=False)
    features.forget(tenant_a.pk)
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head, alexandria)
    here = make_employee(tenant_a, 1, branch=head, department_id=sales.pk)
    make_employee(tenant_a, 2, branch=alexandria, department_id=sales.pk)
    member = make_member(tenant_a, "local", "manager", branches=[head])
    with tenant_context(tenant_a.id):
        data = {"frequency": "monthly", "day": date(2026, 10, 15), "scope": "department",
                "scope_id": sales.pk}
        run = runs.create_run(runs.RunInput(**data, scope_branch_id=head.pk), actor=_actor(member))
        assert [slip.employee_id for slip in run.payslips.all()] == [here.pk]
        with pytest.raises(PermissionDenied):
            runs.create_run(runs.RunInput(**data), actor=_actor(member))


def test_a_given_batch_remembers_its_branch(tenant_a, branches, make_employee):
    from apps.adjustments.models import AdjustmentType
    from apps.adjustments.services import batches

    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save("Sales", head, alexandria)
    here = make_employee(tenant_a, 1, branch=head, department_id=sales.pk)
    make_employee(tenant_a, 2, branch=alexandria, department_id=sales.pk)
    with tenant_context(tenant_a.id):
        kind = AdjustmentType.objects.filter(kind="incentive").first()
        batch = batches.give(batches.AdjustmentInput(
            type_id=kind.pk, target=Target(DEPARTMENT, sales.pk, head.pk),
            date=timezone.localdate(), method="fixed", quantity=100))
        assert batch.target_branch_id == head.pk
        assert [row.employee_id for row in batch.rows.all()] == [here.pk]
