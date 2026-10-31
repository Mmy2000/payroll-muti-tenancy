"""A role that can't work says so: what a permission needs, where it counts, and what the plan
switched off."""

import pytest
from django.utils import translation

from apps.core.errors import ValidationError
from apps.core.tenancy import tenant_context
from apps.iam import selectors, services
from apps.iam.authz import build_actor
from apps.iam.catalog import permissions
from apps.iam.flow import FLOW, missing_needs, needs
from apps.iam.models import Membership, Role
from apps.org.models import Branch
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from config.context_processors import NAVIGATION
from conftest import login

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


def _owner(tenant):
    return build_actor(Membership.objects.get(username="owner"))


def test_managing_needs_seeing():
    assert needs("org.branch.manage") == ("org.branch.view",)
    assert missing_needs(["org.branch.manage"]) == {"org.branch.manage": ("org.branch.view",)}
    assert missing_needs(["org.branch.view", "org.branch.manage"]) == {}


def test_needs_cross_screens_and_chain():
    assert needs("employees.salary.manage") == ("employees.salary.read",
                                                "employees.employee.view")
    assert needs("admin.roles.manage") == ("admin.users.view",)


def test_every_need_is_a_real_permission():
    catalog = permissions()
    for code in catalog:
        assert set(needs(code)) <= set(catalog), code


def test_a_screens_steps_need_what_opens_it_in_the_sidebar():
    """The sidebar shows a screen by one permission. Every step of that screen must lead to it,
    or a role could hold the step and never find the screen."""
    opens = {str(item.label): item.permission for section in NAVIGATION for item in section.items
             if isinstance(item.permission, str) and item.permission != "authenticated"}
    for section in FLOW:
        for screen in section.screens:
            gate = opens.get(str(screen.title))
            for code in screen.codes if gate else ():
                assert code == gate or gate in needs(code), (code, gate)


def test_a_role_with_manage_and_no_view_is_refused(tenant_a):
    with tenant_context(tenant_a.id):
        with pytest.raises(ValidationError) as refused:
            services.create_role("Manager", "", ["org.branch.manage"], actor=_owner(tenant_a))
        assert refused.value.code == "IAM_PERMISSION_NEEDS"
        assert "View branches" in refused.value.fields["permissions"][0]
        assert not Role.objects.filter(name="Manager").exists()


def test_the_api_says_what_is_missing(tenant_a):
    response = login(tenant_a, language="en").post(
        "/api/web/iam/roles/", {"name": "Manager", "permissions": ["admin.users.manage"]},
        content_type="application/json")
    assert response.status_code == 400
    assert "View users" in response.content.decode()


def test_a_whole_role_saves(tenant_a):
    with tenant_context(tenant_a.id):
        role = services.create_role("Manager", "", ["org.branch.view", "org.branch.manage"],
                                    actor=_owner(tenant_a))
        assert role.pk


def test_an_existing_role_with_a_gap_shows_it(tenant_a):
    with tenant_context(tenant_a.id):
        role = services.create_role("Old", "", ["admin.users.manage"])  # from before this rule
    client = login(tenant_a, language="en")
    page = client.get(f"/settings/roles/{role.pk}/").content.decode()
    assert "can't work yet" in page and "View users" in page and "data-add-missing" in page
    assert "Incomplete" in client.get("/settings/roles/").content.decode()


def test_a_whole_role_shows_no_warning(tenant_a):
    with tenant_context(tenant_a.id):
        role = services.create_role("Whole", "", ["org.branch.view", "org.branch.manage"])
    page = login(tenant_a, language="en").get(f"/settings/roles/{role.pk}/").content.decode()
    assert "can't work yet" not in page


def test_the_user_form_warns_what_needs_every_branch(tenant_a):
    with tenant_context(tenant_a.id):
        role = services.create_role("Admin", "", ["admin.users.view", "admin.users.manage"])
        labels = selectors.company_wide_labels({"admin.users.view", "admin.users.manage",
                                                "org.branch.view"})
        assert sorted(map(str, labels)) == ["Manage users and their roles", "View users"]
    page = login(tenant_a, language="en").get("/settings/users/new/").content.decode()
    row = page[page.index(f'data-role-row="{role.pk}"'):]
    assert "data-scope-warning" in row[:row.index("data-role-row", 20)]


def test_the_warning_is_open_for_a_role_given_for_some_branches(tenant_a, make_member):
    member = make_member(tenant_a, "local", "manager")
    with tenant_context(tenant_a.id):
        services.assign_role(member, Role.objects.get(code="manager"),
                             branches=[Branch.objects.get(code=1)])
    page = login(tenant_a, language="en").get(f"/settings/users/{member.pk}/").content.decode()
    start = page.index("data-scope-warning") - 120
    assert "hidden" not in page[start:page.index("data-scope-warning")]


def test_the_role_page_marks_what_the_plan_switched_off(tenant_a):
    TenantFeature.objects.create(tenant=tenant_a, key="loans", enabled=False)
    features.forget(tenant_a.pk)
    page = login(tenant_a, language="en").get("/settings/roles/new/").content.decode()
    assert "Not in your plan" in page
