import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.tenancy import tenant_context
from apps.iam.authz import Actor, build_actor
from apps.iam.catalog import WILDCARD, is_known_permission, permissions
from apps.iam.models import Role
from apps.iam.services import set_role_permissions
from apps.org.models import Branch
from conftest import login


class TestActor:
    def test_all_branches_scope(self):
        actor = Actor(user=None, membership=None, grants={"x.view": None})
        assert actor.can("x.view") and actor.can("x.view", branch=7)
        assert not actor.can("x.edit")

    def test_branch_scope(self):
        actor = Actor(user=None, membership=None, grants={"x.view": frozenset({1, 2})})
        assert actor.can("x.view", branch=1)
        assert not actor.can("x.view", branch=3)
        assert actor.can("x.view")  # tenant-wide question: granted somewhere
        assert actor.branch_ids("x.view") == frozenset({1, 2})

    def test_wildcard(self):
        actor = Actor(user=None, membership=None, grants={WILDCARD: None})
        assert actor.can("anything.at.all", branch=5)
        assert actor.branch_ids("anything") is None


@pytest.mark.django_db
class TestRoles:
    def test_system_roles_seeded_and_owner_assigned(self, tenant_a):
        with tenant_context(tenant_a.id):
            assert set(Role.objects.values_list("code", flat=True)) == {
                "owner", "manager", "viewer", "employee"}
            from apps.iam.models import Membership

            actor = build_actor(Membership.objects.get(username="owner"))
            assert actor.can("org.settings.manage")

    def test_viewer_can_view_but_not_change(self, tenant_a, make_member):
        membership = make_member(tenant_a, "val", "viewer")
        with tenant_context(tenant_a.id):
            actor = build_actor(membership)
        assert actor.can("org.branch.view")
        assert not actor.can("org.branch.manage")
        assert not actor.can("admin.users.manage")

    def test_branch_scoped_assignment(self, tenant_a, make_member):
        with tenant_context(tenant_a.id):
            second = Branch.objects.create(code=2, name="Second")
        membership = make_member(tenant_a, "sam", "manager", branches=[second])
        with tenant_context(tenant_a.id):
            actor = build_actor(membership)
            head = Branch.objects.get(code=1)
        assert actor.can("org.department.manage", branch=second)
        assert not actor.can("org.department.manage", branch=head)
        assert not actor.can("org.settings.manage")  # about the whole client

    def test_owner_role_is_locked_and_unknown_codes_rejected(self, tenant_a):
        from apps.core.errors import ValidationError

        with tenant_context(tenant_a.id):
            with pytest.raises(ValidationError):
                set_role_permissions(Role.objects.get(code="owner"), ["org.branch.view"])
            with pytest.raises(ValidationError):
                set_role_permissions(Role.objects.get(code="viewer"), ["no.such.permission"])


def test_catalog_codes_are_well_formed():
    for code in permissions():
        assert code.count(".") >= 1 and code == code.lower()
    assert is_known_permission("org.branch.manage")
    assert not is_known_permission("org.branch.publish")


def _api_views(patterns=None, prefix=""):
    for entry in patterns if patterns is not None else get_resolver("config.urls").url_patterns:
        if isinstance(entry, URLResolver):
            yield from _api_views(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern) and (prefix + str(entry.pattern)).startswith("api/"):
            yield prefix + str(entry.pattern), entry.callback


def test_every_api_action_declares_a_permission():
    """A view without `required_permissions` for an action is denied at runtime; this
    makes the omission a test failure instead of a silent 403. (The mobile app's /api/v1/
    has its own rule: apps/mobile/tests.)"""
    missing = []
    for route, callback in _api_views():
        cls = getattr(callback, "cls", None)
        if cls is None or not route.startswith("api/web/"):
            continue
        declared = getattr(cls, "required_permissions", {}) or {}
        actions = getattr(callback, "actions", None)
        if actions:
            keys = set(actions.values())
        else:
            keys = {m.upper() for m in cls.http_method_names
                    if hasattr(cls, m) and m not in ("options", "head")}
        for key in keys:
            code = declared.get(key)
            if code is None or not (is_known_permission(code) or code == "authenticated"):
                missing.append(f"{route} {key}")
    assert missing == []


def test_every_api_view_enforces_the_declared_permissions():
    """Declaring `required_permissions` is not enough: a view (or a library base class) that
    sets its own `permission_classes` skips HasTenantPermission. drf-spectacular's schema view
    did, and published the API schema to anyone."""
    from apps.core.api.permissions import HasTenantPermission

    skipping = sorted({route for route, callback in _api_views()
                       if route.startswith("api/web/") and getattr(callback, "cls", None)
                       and HasTenantPermission not in callback.cls.permission_classes})
    assert skipping == []


@pytest.mark.django_db
def test_the_api_schema_is_for_signed_in_members_only(tenant_a):
    from django.test import Client

    anonymous = Client(HTTP_HOST="alpha.localhost").get("/api/web/schema/")
    assert anonymous.status_code in (401, 403)
    assert login(tenant_a).get("/api/web/schema/").status_code == 200


@pytest.mark.django_db
class TestEnforcement:
    def test_viewer_cannot_add_a_branch(self, tenant_a, make_member):
        make_member(tenant_a, "val", "viewer")
        client = login(tenant_a, "val")
        response = client.post("/api/web/org/branches/", {"code": 5, "name": "Giza"},
                               content_type="application/json")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
        assert client.get("/api/web/org/branches/").status_code == 200

    def test_web_pages_respect_permissions(self, tenant_a, make_member):
        make_member(tenant_a, "val", "viewer")
        client = login(tenant_a, "val")
        assert client.get("/branches/").status_code == 200
        assert client.get("/branches/new/").status_code == 403
        assert client.get("/settings/company/").status_code == 403

    def test_navigation_hides_what_you_cannot_open(self, tenant_a, make_member):
        with tenant_context(tenant_a.id):
            role = Role.objects.create(code="branches-only", name="Branches only")
            set_role_permissions(role, ["org.branch.view"])
        member = make_member(tenant_a, "pat", "viewer")
        with tenant_context(tenant_a.id):
            member.roles.all().delete()
            from apps.iam.services import assign_role

            assign_role(member, role)
        html = login(tenant_a, "pat").get("/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
        assert 'href="/branches/"' in html
        assert 'href="/settings/users/"' not in html
        assert 'href="/settings/company/"' not in html
