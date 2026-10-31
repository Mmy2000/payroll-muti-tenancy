"""Each department belongs to one branch, as in PayRole (`Pfn.br1`): a branch has its own
departments, and an employee's department is in the employee's branch."""

import pytest
from django.urls import reverse

from apps.core.errors import PermissionDenied, ValidationError
from apps.core.tenancy import tenant_context
from apps.employees.services import employees
from apps.org import services
from apps.org.models import Branch
from conftest import login

from .. import selectors

pytestmark = pytest.mark.django_db


@pytest.fixture
def branches(tenant_a):
    with tenant_context(tenant_a.id):
        return Branch.objects.get(code=1), Branch.objects.create(code=2, name="Alexandria")


def _save(branch, name, code=None, **kwargs):
    return services.save_department(
        services.DepartmentInput(branch_id=branch.pk, code=code, name=name), **kwargs)


def test_codes_and_names_are_each_branchs_own(tenant_a, branches):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        first = _save(head, "Sales")
        second = _save(head, "Accounts")
        assert (first.code, second.code) == (1, 2)  # the branch's next code
        # The same name and code are another department in another branch.
        other = _save(alexandria, "Sales", code=1)
        assert other.pk != first.pk and other.label == "Sales · Alexandria"

        with pytest.raises(ValidationError) as refused:
            _save(head, "Sales")
        assert "name" in refused.value.fields
        with pytest.raises(ValidationError) as refused:
            _save(head, "Stores", code=1)
        assert "code" in refused.value.fields


def test_a_department_with_employees_stays_in_its_branch(tenant_a, branches, make_employee):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        sales = _save(head, "Sales")
        empty = _save(head, "Empty")
    make_employee(tenant_a, 1, department_id=sales.pk)
    with tenant_context(tenant_a.id):
        with pytest.raises(ValidationError) as refused:
            services.save_department(
                services.DepartmentInput(branch_id=alexandria.pk, name="Sales"),
                department_id=sales.pk)
        assert "branch" in refused.value.fields
        moved = services.save_department(
            services.DepartmentInput(branch_id=alexandria.pk, name="Empty"),
            department_id=empty.pk)
        assert moved.branch_id == alexandria.pk and moved.code == empty.code


def test_an_employees_department_is_in_their_branch(tenant_a, branches, make_employee):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        there = _save(alexandria, "Sales")
    with pytest.raises(ValidationError) as refused:
        make_employee(tenant_a, 1, branch=head, department_id=there.pk)
    assert "department_id" in refused.value.fields
    person = make_employee(tenant_a, 2, branch=alexandria, department_id=there.pk)

    # Moved to another branch, the department has to change with them.
    with tenant_context(tenant_a.id):
        card = employees.EmployeeInput(code=2, name=person.name, branch_id=head.pk,
                                       hired_on=person.hired_on, department_id=there.pk)
        with pytest.raises(ValidationError) as refused:
            employees.update_employee(person.pk, card)
        assert "department_id" in refused.value.fields


def test_a_branch_manager_only_has_their_branchs_departments(tenant_a, branches, make_member):
    from apps.iam.authz import build_actor

    head, alexandria = branches
    with tenant_context(tenant_a.id):
        here = _save(head, "Sales")
        there = _save(alexandria, "Warehouse")
    boss = make_member(tenant_a, "boss", "owner", branches=[head])
    client = login(tenant_a, "boss", language="en")

    with tenant_context(tenant_a.id):
        actor = build_actor(boss)
        assert list(selectors.visible_departments(actor)) == [here]
        with pytest.raises(PermissionDenied):
            _save(alexandria, "Stores", actor=actor)
        with pytest.raises(PermissionDenied):
            services.set_department_active(there.pk, False, actor=actor)

    page = client.get(reverse("departments")).content.decode()
    assert "Sales" in page and "Warehouse" not in page
    assert client.get(reverse("department-edit", args=[there.pk])).status_code == 404
    assert client.get(reverse("department-detail", args=[there.pk])).status_code == 404
    listed = client.get(reverse("department-list")).json()["results"]
    assert [row["id"] for row in listed] == [here.pk]


def test_the_pages_show_each_branchs_departments(tenant_a, branches):
    head, alexandria = branches
    with tenant_context(tenant_a.id):
        _save(head, "Sales")
        _save(alexandria, "Warehouse")
    client = login(tenant_a, language="en")

    response = client.post(reverse("department-list"),
                           {"branch": alexandria.pk, "name": "Stores", "code": None},
                           content_type="application/json")
    assert response.status_code == 201
    assert response.json()["branch_name"] == "Alexandria" and response.json()["code"] == 2

    filtered = client.get(f"{reverse('departments')}?branch={alexandria.pk}").content.decode()
    assert "Warehouse" in filtered and "Sales" not in filtered
    page = client.get(reverse("branch-edit", args=[alexandria.pk])).content.decode()
    assert "Warehouse" in page and "Stores" in page and "Sales" not in page
    page = client.get(f"{reverse('department-new')}?branch={alexandria.pk}").content.decode()
    assert f'value="{alexandria.pk}" selected' in page

    # An employee's form tells each department's branch, for the list to follow the branch.
    page = client.get(reverse("employee-new")).content.decode()
    assert f'data-parent="{alexandria.pk}"' in page and 'data-depends-on="branch_id"' in page


def test_the_employee_import_finds_the_department_in_the_rows_branch(tenant_a, branches):
    from apps.employees.imports import EmployeeImport

    head, alexandria = branches
    with tenant_context(tenant_a.id):
        _save(head, "Sales", code=5)
        there = _save(alexandria, "Sales", code=5)
        sheet = EmployeeImport.__new__(EmployeeImport)
        sheet.prepare()
        assert sheet.departments[alexandria.pk][5] == there.pk
        assert 9 not in sheet.departments[head.pk]


def test_a_branch_comes_first_wherever_a_department_is_chosen(tenant_a, branches):
    """The browser locks a department until its branch is chosen (selects.js `data-depends-on`):
    each form names the field it follows, and each department its branch."""
    _head, alexandria = branches
    with tenant_context(tenant_a.id):
        _save(alexandria, "Warehouse")
    client = login(tenant_a, language="en")
    for url, parent in ((reverse("employee-new"), "branch_id"),
                        (reverse("employees"), "branch"),
                        (reverse("attendance"), "branch"),
                        (reverse("incentive-new"), "target_department_branch"),
                        (reverse("hourly-leave-for-group"), "group_department_branch"),
                        (reverse("payroll-run-new"), "scope_department_branch")):
        page = client.get(url).content.decode()
        assert f'data-depends-on="{parent}"' in page, url
        assert f'name="{parent}"' in page, url
        assert f'data-parent="{alexandria.pk}"' in page, url

    # A new employee starts with no branch, or the department would be open from the start.
    page = client.get(reverse("employee-new")).content.decode()
    assert ('<select id="f-branch" name="branch_id" class="form-input">\n'
            '              <option value="">') in page


def test_with_one_branch_there_is_nothing_to_choose_first(tenant_a):
    with tenant_context(tenant_a.id):
        _save(Branch.objects.get(code=1), "Sales")
    client = login(tenant_a, language="en")
    page = client.get(reverse("incentive-new")).content.decode()
    assert 'name="target_department_branch"' not in page and "Sales" in page
    page = client.get(reverse("employee-new")).content.decode()
    assert '<select id="f-branch" name="branch_id" class="form-input">\n              \n' in page
