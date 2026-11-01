"""Undo and redo on the company structure page: exact, safe, and the member's own."""

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone, translation

from apps.core.errors import NotFound, PermissionDenied
from apps.core.tenancy import tenant_context
from apps.employees import selectors
from apps.employees.models import Employee, EmployeeAssignment, StructureChange
from apps.employees.services import structure
from apps.employees.services import structure_history as history
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
        sales = org.save_department(org.DepartmentInput("Sales", (head.pk, far.pk)))
        stores = org.save_department(org.DepartmentInput("Stores", (head.pk,)))
    sara = make_employee(tenant_a, 1, branch=head, department_id=sales.pk, name="Sara")
    omar = make_employee(tenant_a, 2, branch=head, department_id=stores.pk, name="Omar")
    return {"head": head, "far": far, "sales": sales, "stores": stores, "sara": sara, "omar": omar}


def _owner():
    return build_actor(Membership.objects.get(username="owner"))


def _rows(employee):
    return list(EmployeeAssignment.objects.filter(employee=employee).order_by("effective_from")
                .values_list("effective_from", "branch_id", "department_id", "note"))


def _card(employee):
    person = Employee.objects.get(pk=employee.pk)
    return person.branch_id, person.department_id


def _last():
    return StructureChange.objects.order_by("-pk").first()


def test_undo_takes_a_move_back_exactly_and_redo_makes_it_again(tenant_a, company):
    sara, far = company["sara"], company["far"]
    with tenant_context(tenant_a.id):
        before, card = _rows(sara), _card(sara)
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, note="Opening",
                              actor=_owner())
        moved = _rows(sara)
        assert history.undo(_last().pk, actor=_owner())["done"]
        assert _rows(sara) == before and _card(sara) == card  # no extra row in their history
        assert history.redo(_last().pk, actor=_owner())["done"]
        assert _rows(sara) == moved and _card(sara) == (far.pk, company["sales"].pk)


def test_undo_brings_back_a_row_a_same_day_move_replaced(tenant_a, company):
    sara, far, head = company["sara"], company["far"], company["head"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, note="First",
                              actor=_owner())
        first = _rows(sara)
        structure.move_people([sara.pk], head.pk, None, DAY, note="Second", actor=_owner())
        assert history.undo(_last().pk, actor=_owner())["done"]
        assert _rows(sara) == first


def test_undo_returns_a_department_and_its_people_to_their_branch(tenant_a, company):
    stores, omar, head, far = company["stores"], company["omar"], company["head"], company["far"]
    with tenant_context(tenant_a.id):
        structure.move_department(stores.pk, head.pk, far.pk, DAY, actor=_owner())
        assert Department.objects.get(pk=stores.pk).branch_ids == [far.pk]
        assert history.undo(_last().pk, actor=_owner())["done"]
        assert Department.objects.get(pk=stores.pk).branch_ids == [head.pk]
        assert _card(omar) == (head.pk, stores.pk)
        assert history.redo(_last().pk, actor=_owner())["done"]
        assert Department.objects.get(pk=stores.pk).branch_ids == [far.pk]
        assert _card(omar) == (far.pk, stores.pk)


def test_undo_puts_a_removed_department_back_with_its_people(tenant_a, company):
    sales, sara, head = company["sales"], company["sara"], company["head"]
    with tenant_context(tenant_a.id):
        structure.remove_department(sales.pk, head.pk, company["stores"].pk, DAY, actor=_owner())
        assert _card(sara) == (head.pk, company["stores"].pk)
        assert history.undo(_last().pk, actor=_owner())["done"]
        assert head.pk in Department.objects.get(pk=sales.pk).branch_ids
        assert _card(sara) == (head.pk, sales.pk)


def test_undo_of_adding_a_department_is_refused_once_people_work_in_it(tenant_a, company):
    stores, far, sara = company["stores"], company["far"], company["sara"]
    with tenant_context(tenant_a.id):
        structure.add_department(stores.pk, far.pk, actor=_owner())
        added = _last().pk
        structure.move_people([sara.pk], far.pk, stores.pk, DAY, actor=_owner())
        result = history.undo(added, actor=_owner())
        assert not result["done"] and result["message"]
        assert far.pk in Department.objects.get(pk=stores.pk).branch_ids
        assert not StructureChange.objects.filter(pk=added).exists()


def test_undo_never_overwrites_a_change_made_since(tenant_a, company):
    sara, far = company["sara"], company["far"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        change = _last().pk
        EmployeeAssignment.objects.filter(employee=sara, effective_from=DAY).update(
            note="Edited elsewhere")
        now = _rows(sara)
        assert not history.undo(change, actor=_owner())["done"]
        assert _rows(sara) == now and not StructureChange.objects.filter(pk=change).exists()


def test_undo_stops_at_a_later_move(tenant_a, company):
    sara, far, head = company["sara"], company["far"], company["head"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        first = _last().pk
        structure.move_people([sara.pk], head.pk, company["sales"].pk, date(2026, 7, 1),
                              actor=_owner())
        assert not history.undo(first, actor=_owner())["done"]
        assert _card(sara) == (head.pk, company["sales"].pk)


def test_a_failed_undo_changes_nothing_at_all(tenant_a, company):
    sara, omar, far = company["sara"], company["omar"], company["far"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk, omar.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        change = _last().pk
        EmployeeAssignment.objects.filter(employee=omar, effective_from=DAY).update(note="Edited")
        assert not history.undo(change, actor=_owner())["done"]
        assert _card(sara) == (far.pk, company["sales"].pk)


def test_an_approved_payroll_keeps_its_days(tenant_a, company, monkeypatch):
    sara, far = company["sara"], company["far"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        change = _last().pk
        monkeypatch.setattr("apps.core.locks.period_locked", lambda *args: True)
        with translation.override("en"):
            result = history.undo(change, actor=_owner())
        assert not result["done"] and "payroll" in result["message"].lower()
        assert _card(sara) == (far.pk, company["sales"].pk)


def test_only_the_member_who_made_it_can_undo_it(tenant_a, company, make_member):
    sara, far = company["sara"], company["far"]
    other = make_member(tenant_a, "other", "manager", branches=[company["head"], far])
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        someone_else = build_actor(Membership.objects.get(pk=other.pk))
        with pytest.raises(NotFound):
            history.undo(_last().pk, actor=someone_else)
        assert selectors.structure_history(someone_else)["undo"] == []
        assert _card(sara) == (far.pk, company["sales"].pk)


def test_undo_needs_the_permissions_of_today(tenant_a, company, monkeypatch):
    sara, far = company["sara"], company["far"]
    with tenant_context(tenant_a.id):
        owner = _owner()
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=owner)

        def refuse(*args, **kwargs):
            raise PermissionDenied("No.")

        restricted = _owner()
        monkeypatch.setattr(type(restricted), "require", refuse)
        with pytest.raises(PermissionDenied):
            history.undo(_last().pk, actor=restricted)
        assert StructureChange.objects.filter(pk=_last().pk).exists()


def test_a_new_change_ends_what_could_be_redone(tenant_a, company):
    sara, far, head = company["sara"], company["far"], company["head"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        history.undo(_last().pk, actor=_owner())
        assert len(selectors.structure_history(_owner())["redo"]) == 1
        structure.move_people([sara.pk], head.pk, None, DAY, actor=_owner())
        assert selectors.structure_history(_owner())["redo"] == []


def test_nothing_is_kept_for_a_move_that_changed_nothing(tenant_a, company):
    with tenant_context(tenant_a.id):
        structure.add_department(company["sales"].pk, company["far"].pk, actor=_owner())
        assert not StructureChange.objects.exists()


def test_only_the_latest_changes_are_kept(tenant_a, company, monkeypatch):
    monkeypatch.setattr(history, "KEPT", 2)
    sara, far, head = company["sara"], company["far"], company["head"]
    with tenant_context(tenant_a.id):
        for place in (far, head, far):
            structure.move_people([sara.pk], place.pk, company["sales"].pk, DAY, actor=_owner())
        assert StructureChange.objects.count() == 2


def test_the_history_names_each_change(tenant_a, company):
    sara, far = company["sara"], company["far"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, DAY, actor=_owner())
        structure.add_department(company["stores"].pk, far.pk, actor=_owner())
        labels = [item["label"] for item in selectors.structure_history(_owner())["undo"]]
    assert any("Stores" in label and "Alexandria" in label for label in labels)
    assert any("Sara" in label and "Sales" in label for label in labels)


def test_undo_through_the_api(tenant_a, company):
    sara, far = company["sara"], company["far"]
    with tenant_context(tenant_a.id):
        structure.move_people([sara.pk], far.pk, company["sales"].pk, timezone.localdate(),
                              actor=_owner())
        change = _last().pk
    client = login(tenant_a, language="en")
    host = {"HTTP_HOST": f"{tenant_a.slug}.localhost"}
    response = client.post(reverse("structure-undo"), {"change_id": change},
                           content_type="application/json", **host)
    assert response.status_code == 200 and response.json()["done"] is True
    with tenant_context(tenant_a.id):
        assert _card(sara) == (company["head"].pk, company["sales"].pk)
