"""Where a permission holds. A member limited to some branches can't reach beyond them, and
permissions about the whole client count only in every branch."""

import pytest

from apps.core.errors import PermissionDenied, ValidationError
from apps.core.tenancy import tenant_context
from apps.employees.permissions import VIEW
from apps.iam import limits, services
from apps.iam.authz import Actor, build_actor, members_who_can
from apps.iam.models import Membership, Role
from apps.iam.validators import ensure_can_grant, is_superior
from apps.mobile.services import access
from apps.mobile.tests.test_contract import _switch
from apps.org import services as org
from apps.org.models import Branch
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db
EVERY_BRANCH = None


@pytest.fixture
def branches(tenant_a):
    with tenant_context(tenant_a.id):
        return Branch.objects.get(code=1), org.create_branch(org.BranchInput(code=2, name="B"))


def _member(tenant, make_member, name, codes, scope):
    member = make_member(tenant, name, "viewer")
    with tenant_context(tenant.id):
        member.roles.all().delete()
        role = services.create_role(f"Role {name}", "", codes)
        services.assign_role(member, role, branches=scope)
    return member, role


def _actor(member):
    return build_actor(Membership.objects.get(pk=member.pk))


def _details(member, *roles):
    return services.MemberInput(username=member.username, display_name=member.user.display_name,
                                email=member.user.email, roles=roles)


def test_an_empty_scope_holds_nothing():
    actor = Actor(user=None, membership=None, grants={"loans.loan.view": frozenset()})
    assert not actor.can("loans.loan.view")


def test_a_company_wide_permission_counts_only_in_every_branch(tenant_a, branches, make_member):
    a, _b = branches
    limited, _role = _member(tenant_a, make_member, "one", ["admin.users.manage", VIEW], [a])
    full, _role = _member(tenant_a, make_member, "all", ["admin.users.manage"], EVERY_BRANCH)
    with tenant_context(tenant_a.id):
        assert not _actor(limited).can("admin.users.manage")
        assert not _actor(limited).can("admin.users.manage", branch=a)
        assert _actor(limited).can(VIEW, branch=a)  # an ordinary permission is unchanged
        assert _actor(limited).branch_ids("admin.users.manage") == frozenset()
        assert _actor(full).can("admin.users.manage", branch=a)
        told = set(members_who_can("admin.users.manage").values_list("pk", flat=True))
        assert full.pk in told and limited.pk not in told


def test_a_branch_limited_member_cant_touch_a_branch_or_list_users(tenant_a, branches,
                                                                   make_member):
    a, b = branches
    member, _role = _member(tenant_a, make_member, "one",
                            ["org.branch.manage", "admin.users.view"], [a])
    with tenant_context(tenant_a.id), pytest.raises(PermissionDenied):
        org.set_branch_active(b.pk, False, actor=_actor(member))
    client = login(tenant_a, "one")
    assert client.get("/api/web/iam/members/").status_code == 403


def test_nobody_grants_beyond_where_they_hold_a_permission(tenant_a, branches, make_member):
    a, b = branches
    member, role = _member(tenant_a, make_member, "one", [VIEW], [a])
    with tenant_context(tenant_a.id):
        actor = _actor(member)
        ensure_can_grant(actor, [VIEW], {a.pk})
        for where in ({b.pk}, {a.pk, b.pk}, EVERY_BRANCH):
            with pytest.raises(PermissionDenied):
                ensure_can_grant(actor, [VIEW], where)


def test_a_user_manager_cant_widen_their_own_scope(tenant_a, branches, make_member):
    a, _b = branches
    member, role = _member(tenant_a, make_member, "hr", [VIEW], [a])
    with tenant_context(tenant_a.id):
        manage = services.create_role("Users", "", ["admin.users.manage"])
        services.assign_role(member, manage, branches=EVERY_BRANCH)
        actor = _actor(member)
        with pytest.raises(PermissionDenied):
            services.update_member(member.pk, _details(
                member, services.RoleAssignmentInput(role.pk, None),
                services.RoleAssignmentInput(manage.pk, None)), actor=actor)
        assert _actor(member).branch_ids(VIEW) == frozenset({a.pk})


def test_taking_a_branch_away_needs_that_branch(tenant_a, branches, make_member):
    a, b = branches
    target, role = _member(tenant_a, make_member, "target", [VIEW], [a, b])
    member, _own = _member(tenant_a, make_member, "hr", [VIEW], [a])
    with tenant_context(tenant_a.id):
        manage = services.create_role("Users", "", ["admin.users.manage"])
        services.assign_role(member, manage, branches=EVERY_BRANCH)
        with pytest.raises(PermissionDenied):
            services.update_member(target.pk, _details(
                target, services.RoleAssignmentInput(role.pk, (a.pk,))), actor=_actor(member))


def test_an_owner_limited_to_a_branch_is_not_superior(tenant_a, branches, make_member):
    a, b = branches
    member = make_member(tenant_a, "minor", "owner", branches=[a])
    with tenant_context(tenant_a.id):
        actor = _actor(member)
        assert not is_superior(actor)
        assert not actor.can("admin.users.manage")
        with pytest.raises(PermissionDenied):
            ensure_can_grant(actor, [VIEW], {b.pk})


def test_the_owner_role_covers_every_branch(tenant_a, branches, make_member):
    a, _b = branches
    member = make_member(tenant_a, "someone", "viewer")
    with tenant_context(tenant_a.id):
        owner = Role.objects.get(code="owner")
        with pytest.raises(ValidationError) as refused:
            services.update_member(member.pk, _details(
                member, services.RoleAssignmentInput(owner.pk, (a.pk,))))
        assert "roles" in refused.value.fields


def test_a_role_needs_at_least_one_branch(tenant_a, branches, make_member):
    member = make_member(tenant_a, "someone", "viewer")
    with tenant_context(tenant_a.id):
        viewer = Role.objects.get(code="viewer")
        with pytest.raises(ValidationError) as refused:
            services.update_member(member.pk, _details(
                member, services.RoleAssignmentInput(viewer.pk, ())))
        assert "roles" in refused.value.fields


def test_only_owners_of_every_branch_count_as_the_last_owner(tenant_a, branches, make_member):
    a, _b = branches
    make_member(tenant_a, "minor", "owner", branches=[a])
    with tenant_context(tenant_a.id):
        owner = Membership.objects.get(username="owner")
        with pytest.raises(ValidationError) as refused:
            services.set_member_status(owner.pk, "suspended")
        assert refused.value.code == "IAM_LAST_OWNER"


def test_the_employee_role_stays_an_app_login(tenant_a, make_employee):
    _switch(tenant_a)
    person = make_employee(tenant_a, 7)
    with tenant_context(tenant_a.id):
        access.give_login(person.pk, "app", PASSWORD)
        role = Role.objects.get(code="employee")
        with pytest.raises(ValidationError) as refused:
            services.update_role(role.pk, role.name, "", ["mobile.signin", "admin.users.manage"])
        assert refused.value.code == "IAM_EMPLOYEE_LOCKED"
        services.update_role(role.pk, "Field staff", "", ["mobile.signin"])  # its name may change
        assert limits.app_logins() == 1
