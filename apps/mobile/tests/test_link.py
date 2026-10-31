"""A user linked to the employee they are (PayRole: the user's `emp`), from the user's form: the
office user who is also an employee uses the app as that employee."""

from datetime import date

import pytest
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.employees.models import Employee
from apps.iam.models import Membership, MembershipStatus, Role
from apps.mobile.tests.test_contract import App, _switch
from conftest import PASSWORD, login

from ..services import access

pytestmark = pytest.mark.django_db


def _body(member, **extra):
    role = Role.objects.get(code="manager")
    return {"username": member.username, "display_name": member.user.display_name,
            "email": member.user.email or "", "phone": "", "default_branch": None,
            "roles": [{"role": role.pk, "all_branches": True, "branches": []}], **extra}


def _save(client, member, **extra):
    return client.put(reverse("member-detail", args=[member.pk]), _body(member, **extra),
                      content_type="application/json")


@pytest.fixture
def office(tenant_a, make_member, make_employee):
    _switch(tenant_a)
    samir = make_employee(tenant_a, 1, name="Samir")
    hany = make_employee(tenant_a, 2, name="Hany")
    member = make_member(tenant_a, "samir", "manager")
    return {"samir": samir, "hany": hany, "member": member, "owner": login(tenant_a, language="en")}


def test_a_user_is_linked_to_their_employee_from_the_users_form(tenant_a, office):
    owner, member, samir = office["owner"], office["member"], office["samir"]
    page = owner.get(reverse("user-edit", args=[member.pk])).content.decode()
    assert 'name="employee"' in page and "Samir" in page

    with tenant_context(tenant_a.id):
        assert _save(owner, member, employee=samir.pk).status_code == 200
        assert Employee.objects.get(pk=samir.pk).member_id == member.pk
        # Saving without the field (another client of the API) leaves the link alone.
        assert _save(owner, member).status_code == 200
        assert Employee.objects.get(pk=samir.pk).member_id == member.pk

    # The office user now works in the app as Samir.
    phone = App(tenant_a)
    with tenant_context(tenant_a.id):
        role = Role.objects.get(code="manager")
        from apps.iam.services import set_role_permissions

        set_role_permissions(role, [g.permission for g in role.grants.all()] + ["mobile.signin"])
    assert phone.sign_in("samir").status_code == 200
    assert phone.get("me").json()["employee"]["name"] == "Samir"


def test_linking_moves_and_unlinks(tenant_a, office):
    owner, member, samir, hany = (office[k] for k in ("owner", "member", "samir", "hany"))
    with tenant_context(tenant_a.id):
        _save(owner, member, employee=samir.pk)
        assert _save(owner, member, employee=hany.pk).status_code == 200
        assert Employee.objects.get(pk=samir.pk).member_id is None
        assert Employee.objects.get(pk=hany.pk).member_id == member.pk
        assert _save(owner, member, employee=None).status_code == 200
        assert not Employee.objects.filter(member_id=member.pk).exists()


def test_an_employee_is_one_users_and_must_still_work_here(tenant_a, office, make_member):
    owner, member, samir, hany = (office[k] for k in ("owner", "member", "samir", "hany"))
    other = make_member(tenant_a, "other", "manager")
    with tenant_context(tenant_a.id):
        _save(owner, other, employee=samir.pk)
        response = _save(owner, member, employee=samir.pk)
        assert response.status_code == 400
        assert "other" in response.json()["error"]["fields"]["employee"][0]

        Employee.objects.filter(pk=hany.pk).update(left_on=date(2025, 6, 30))
        response = _save(owner, member, employee=hany.pk)
        assert response.status_code == 400 and response.json()["error"]["fields"]["employee"]
        # Nothing else was saved with the refused link.
        assert Employee.objects.get(pk=samir.pk).member_id == other.pk


def test_a_new_user_and_their_employee_are_saved_together(tenant_a, office):
    owner, samir = office["owner"], office["samir"]
    with tenant_context(tenant_a.id):
        role = Role.objects.get(code="viewer")
        body = {"username": "newbie", "display_name": "Newbie", "email": "", "phone": "",
                "default_branch": None, "password": PASSWORD,
                "roles": [{"role": role.pk, "all_branches": True, "branches": []}]}
        response = owner.post(reverse("member-list"), {**body, "employee": samir.pk},
                              content_type="application/json")
        assert response.status_code == 201
        assert Employee.objects.get(pk=samir.pk).member.username == "newbie"
        # A refused link refuses the whole user.
        response = owner.post(reverse("member-list"),
                              {**body, "username": "second", "employee": samir.pk},
                              content_type="application/json")
        assert response.status_code == 400
        assert not Membership.objects.filter(username="second").exists()


def test_unlinking_an_office_user_keeps_their_login(tenant_a, office):
    owner, member, samir = office["owner"], office["member"], office["samir"]
    with tenant_context(tenant_a.id):
        _save(owner, member, employee=samir.pk)
    page = owner.get(reverse("employee", args=[samir.pk])).content.decode()
    assert "Linked to the user" in page and "Unlink from the user" in page
    assert owner.delete(reverse("app-login-detail", args=[samir.pk])).status_code == 204
    with tenant_context(tenant_a.id):
        assert Membership.objects.get(pk=member.pk).status == MembershipStatus.ACTIVE
        assert Employee.objects.get(pk=samir.pk).member_id is None

        # A login made for the app only stops working when taken away.
        app_login = access.give_login(samir.pk, "samir-app", PASSWORD)
    page = owner.get(reverse("employee", args=[samir.pk])).content.decode()
    assert "Take the login away" in page
    owner.delete(reverse("app-login-detail", args=[samir.pk]))
    with tenant_context(tenant_a.id):
        assert Membership.objects.get(pk=app_login.pk).status == MembershipStatus.SUSPENDED


def test_the_choice_needs_the_app_and_the_actors_branches(tenant_a, office, make_member):
    from apps.org.models import Branch

    owner, member = office["owner"], office["member"]
    with tenant_context(tenant_a.id):
        other_branch = Branch.objects.create(code=2, name="Alexandria")
        Employee.objects.filter(pk=office["hany"].pk).update(branch=other_branch)
        head_office = Branch.objects.get(code=1)
    # A manager of the head office only does not see, nor link, the other branch's employee.
    make_member(tenant_a, "boss", "owner", branches=[head_office])
    boss = login(tenant_a, "boss", language="en")
    page = boss.get(reverse("user-edit", args=[member.pk])).content.decode()
    assert "Samir" in page and "Hany" not in page
    with tenant_context(tenant_a.id):
        assert _save(boss, member, employee=office["hany"].pk).status_code == 404

    # With the mobile app off for the client, the form does not offer the link.
    _switch(tenant_a, mobile_app=False)
    page = owner.get(reverse("user-edit", args=[member.pk])).content.decode()
    assert 'name="employee"' not in page
