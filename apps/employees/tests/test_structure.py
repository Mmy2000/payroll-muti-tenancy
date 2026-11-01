"""The company structure page: what it shows each member, and the moves it makes."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.errors import DomainError, PermissionDenied, ValidationError
from apps.core.tenancy import tenant_context
from apps.employees import selectors
from apps.employees.models import Employee, EmployeeAssignment
from apps.employees.services import employees, structure
from apps.iam.authz import build_actor
from apps.iam.models import Membership
from apps.org import services as org
from apps.org.models import Branch, Department
from conftest import login

pytestmark = pytest.mark.django_db
DAY = date(2026, 6, 1)


@pytest.fixture
def company(tenant_a, make_employee):
    with tenant_context(tenant_a.id):
        head = Branch.objects.get(code=1)
        far = org.create_branch(org.BranchInput(code=2, name="Alexandria"))
        third = org.create_branch(org.BranchInput(code=3, name="Giza"))
        sales = org.save_department(org.DepartmentInput("Sales", (head.pk, far.pk)))
        stores = org.save_department(org.DepartmentInput("Stores", (head.pk,)))
    here = make_employee(tenant_a, 1, branch=head, department_id=sales.pk, name="Sara")
    there = make_employee(tenant_a, 2, branch=far, department_id=sales.pk, name="Omar")
    loose = make_employee(tenant_a, 3, branch=head, name="Nour")
    return {"head": head, "far": far, "third": third, "sales": sales, "stores": stores,
            "here": here, "there": there, "loose": loose}


def _actor(member):
    return build_actor(Membership.objects.get(pk=member.pk))


def _owner():
    return build_actor(Membership.objects.get(username="owner"))


def _branch(tree, branch):
    return next(node for node in tree["branches"] if node["id"] == branch.pk)


def test_the_page_opens_the_workspace_for_the_company(tenant_a, company):
    client = login(tenant_a, language="en")
    response = client.get(reverse("structure"), HTTP_HOST=f"{tenant_a.slug}.localhost")
    assert response.status_code == 200
    assert response.context["config"]["company"] == tenant_a.name
    page = response.content.decode()
    assert "data-canvas" in page and "data-tree" in page  # the canvas, and the list for phones
    assert "employees/js/structure/page" in page


def test_the_tree_counts_each_branchs_own_people(tenant_a, company):
    with tenant_context(tenant_a.id):
        tree = selectors.structure_tree(_owner())
    head = _branch(tree, company["head"])
    sales = next(d for d in head["departments"] if d["name"] == "Sales")
    assert (head["people"], head["unassigned"], sales["people"]) == (2, 1, 1)
    assert _branch(tree, company["far"])["people"] == 1
    assert set(sales["branch_ids"]) == {company["head"].pk, company["far"].pk}


def test_people_who_left_are_not_counted(tenant_a, company):
    with tenant_context(tenant_a.id):
        employees.end_employment(company["here"].pk, date(2026, 1, 31))
        tree = selectors.structure_tree(_owner())
        assert _branch(tree, company["head"])["people"] == 1
        assert selectors.structure_people(_owner(), company["head"].pk, company["sales"].pk) == []


def test_only_who_manages_all_its_branches_is_offered_a_departments_form(tenant_a, company,
                                                                          make_member):
    member = make_member(tenant_a, "local", "manager", branches=[company["head"]])
    with tenant_context(tenant_a.id):
        tree = selectors.structure_tree(_actor(member))
    head = _branch(tree, company["head"])
    by_name = {node["name"]: node for node in head["departments"]}
    assert by_name["Sales"]["edit_url"] == ""  # also in Alexandria
    assert by_name["Stores"]["edit_url"] != ""  # only here
    page = login(tenant_a, "local", language="en").get(
        reverse("branch-edit", args=[company["head"].pk]), HTTP_HOST=f"{tenant_a.slug}.localhost")
    html = page.content.decode()
    assert page.status_code == 200
    assert reverse("department-edit", args=[company["stores"].pk]) in html
    assert reverse("department-edit", args=[company["sales"].pk]) not in html


def test_a_branch_limited_member_sees_their_branch(tenant_a, company, make_member):
    member = make_member(tenant_a, "local", "manager", branches=[company["head"]])
    with tenant_context(tenant_a.id):
        actor = _actor(member)
        tree = selectors.structure_tree(actor)
        assert [node["id"] for node in tree["branches"]] == [company["head"].pk]
        assert selectors.structure_people(actor, company["far"].pk, company["sales"].pk) == []
        found = selectors.structure_search(actor, "Omar")
        assert found == []


def test_moving_someone_is_dated_and_keeps_the_past(tenant_a, company):
    with tenant_context(tenant_a.id):
        structure.move_people([company["here"].pk], company["far"].pk, company["sales"].pk, DAY,
                              note="Needed there")
        rows = list(EmployeeAssignment.objects.filter(employee=company["here"])
                    .order_by("effective_from"))
        assert [(row.effective_from, row.branch_id) for row in rows] == [
            (date(2025, 1, 1), company["head"].pk), (DAY, company["far"].pk)]
        assert rows[1].note == "Needed there"
        assert Employee.objects.get(pk=company["here"].pk).branch_id == company["far"].pk


def test_a_move_keeps_the_job(tenant_a, make_employee, company):
    person = make_employee(tenant_a, 9, branch=company["head"], job_title="Clerk")
    with tenant_context(tenant_a.id):
        structure.move_people([person.pk], company["far"].pk, None, DAY)
        assert Employee.objects.get(pk=person.pk).job_title == "Clerk"


def test_a_second_move_on_a_day_replaces_the_first(tenant_a, company):
    with tenant_context(tenant_a.id):
        for branch in (company["far"], company["third"]):
            structure.move_people([company["loose"].pk], branch.pk, None, DAY)
        assert EmployeeAssignment.objects.filter(employee=company["loose"]).count() == 2
        assert Employee.objects.get(pk=company["loose"].pk).branch_id == company["third"].pk


def test_several_move_together_or_not_at_all(tenant_a, company):
    with tenant_context(tenant_a.id):
        structure.move_people([company["here"].pk, company["loose"].pk], company["far"].pk,
                              company["sales"].pk, DAY)
        assert Employee.objects.filter(branch=company["far"]).count() == 3
        with pytest.raises(ValidationError):  # Stores isn't in Alexandria
            structure.move_people([company["here"].pk, company["there"].pk], company["far"].pk,
                                  company["stores"].pk, date(2026, 7, 1))
        assert not EmployeeAssignment.objects.filter(effective_from=date(2026, 7, 1)).exists()


def test_a_member_cant_move_someone_out_of_reach(tenant_a, company, make_member):
    member = make_member(tenant_a, "local", "manager", branches=[company["head"]])
    with tenant_context(tenant_a.id):
        actor = _actor(member)
        with pytest.raises(PermissionDenied):
            structure.move_people([company["here"].pk], company["far"].pk, None, DAY, actor=actor)


def test_a_department_moves_to_another_branch_with_its_people(tenant_a, company):
    with tenant_context(tenant_a.id):
        moved = structure.move_department(company["sales"].pk, company["far"].pk,
                                          company["third"].pk, DAY)
        assert moved == 1
        sales = Department.objects.get(pk=company["sales"].pk)
        assert set(sales.branch_ids) == {company["head"].pk, company["third"].pk}
        person = Employee.objects.get(pk=company["there"].pk)
        assert (person.branch_id, person.department_id) == (company["third"].pk, sales.pk)
        assert Employee.objects.get(pk=company["here"].pk).branch_id == company["head"].pk


def test_a_department_cant_move_ahead_of_time(tenant_a, company):
    soon = timezone.localdate() + timedelta(days=5)
    with tenant_context(tenant_a.id), pytest.raises(ValidationError):
        structure.move_department(company["sales"].pk, company["far"].pk, company["third"].pk, soon)


def test_removing_a_department_moves_its_people_within_the_branch(tenant_a, company):
    with tenant_context(tenant_a.id):
        structure.remove_department(company["sales"].pk, company["head"].pk,
                                    company["stores"].pk, DAY)
        person = Employee.objects.get(pk=company["here"].pk)
        assert (person.branch_id, person.department_id) == (company["head"].pk,
                                                            company["stores"].pk)
        assert Department.objects.get(pk=company["sales"].pk).branch_ids == [company["far"].pk]


def test_removing_can_leave_people_with_no_department(tenant_a, company):
    with tenant_context(tenant_a.id):
        structure.remove_department(company["sales"].pk, company["far"].pk, None, DAY)
        assert Employee.objects.get(pk=company["there"].pk).department_id is None


def test_a_department_keeps_its_last_branch(tenant_a, company):
    with tenant_context(tenant_a.id), pytest.raises(DomainError) as refused:
        structure.remove_department(company["stores"].pk, company["head"].pk, None, DAY)
    assert refused.value.code == "ORG_LAST_BRANCH"


def test_someone_who_left_doesnt_hold_a_department_in_a_branch(tenant_a, company):
    with tenant_context(tenant_a.id):
        employees.end_employment(company["there"].pk, date(2026, 1, 31))
        structure.remove_department(company["sales"].pk, company["far"].pk, None, DAY)
        leaver = Employee.objects.get(pk=company["there"].pk)
        employees.update_employee(leaver.pk, employees.EmployeeInput(
            code=2, name="Renamed", branch_id=leaver.branch_id, hired_on=leaver.hired_on,
            department_id=leaver.department_id))
        assert Employee.objects.get(pk=leaver.pk).name == "Renamed"


def test_a_department_joins_another_branch(tenant_a, company):
    with tenant_context(tenant_a.id):
        structure.add_department(company["stores"].pk, company["far"].pk)
        assert set(Department.objects.get(pk=company["stores"].pk).branch_ids) == {
            company["head"].pk, company["far"].pk}


def test_department_moves_need_both_branches(tenant_a, company, make_member):
    member = make_member(tenant_a, "local", "manager", branches=[company["head"]])
    with tenant_context(tenant_a.id):
        with pytest.raises(PermissionDenied):
            structure.move_department(company["stores"].pk, company["head"].pk, company["far"].pk,
                                      DAY, actor=_actor(member))


def test_the_page_and_api(tenant_a, company):
    client = login(tenant_a, language="en")
    page = client.get(reverse("structure")).content.decode()
    assert "Company structure" in page and "data-tree" in page
    assert client.get(reverse("structure-list")).json()["branches"]
    people = client.get(reverse("structure-people"), {
        "branch": company["head"].pk, "department": company["sales"].pk}).json()
    assert [person["name"] for person in people] == ["Sara"]
    nobody = client.get(reverse("structure-people"), {"branch": company["head"].pk}).json()
    assert [person["name"] for person in nobody] == ["Nour"]
    found = client.get(reverse("structure-search"), {"q": "om"}).json()
    assert [person["name"] for person in found] == ["Omar"]
    moved = client.post(reverse("structure-move-people"), {
        "employee_ids": [company["loose"].pk], "branch_id": company["far"].pk,
        "department_id": None, "effective_from": "2026-06-01"}, content_type="application/json")
    assert moved.status_code == 200


def test_a_viewer_sees_but_cant_change(tenant_a, company, make_member):
    make_member(tenant_a, "view", "viewer")
    client = login(tenant_a, "view", language="en")
    assert client.get(reverse("structure")).status_code == 200
    assert client.post(reverse("structure-move-department"), {
        "department_id": company["sales"].pk, "from_branch_id": company["far"].pk,
        "branch_id": company["third"].pk, "effective_from": "2026-06-01"},
        content_type="application/json").status_code == 403
