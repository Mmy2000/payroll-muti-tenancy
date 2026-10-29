"""The platform console (phase 8): staff sign-in, signing a client up, its plan, limits, company
settings, addresses, features and status, plans, traffic, jobs and the activity log."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.tenancy import tenant_context
from apps.platform.tenants import features
from apps.platform.tenants.models import (
    Plan,
    PlanFeature,
    PlatformEvent,
    Tenant,
    TenantDomain,
    TenantFeature,
    TenantStatus,
)
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db
HOST = "admin.localhost"


@pytest.fixture
def staff(db):
    from apps.iam.models import User

    User.objects.create_superuser(email="ops@platform.test", password=PASSWORD,
                                  display_name="Ops")
    client = Client(HTTP_HOST=HOST)
    client.cookies["django_language"] = "en"
    response = client.post("/login/", {"username": "ops@platform.test", "password": PASSWORD})
    assert response.status_code == 302
    return client


def _new_client(staff, **overrides):
    data = {"name": "Nile Foods", "slug": "nile", "locale": "ar", "country": "EG",
            "functional_currency": "EGP", "timezone": "Africa/Cairo",
            "owner_display_name": "Samir", "owner_username": "samir",
            "owner_email": "samir@nile.test", "owner_password": "Nile-Owner-2026",
            "plan": "standard", "trial_ends_on": "", "max_branches": "", "max_users": "",
            "contact_name": "Samir", "contact_email": "", "contact_phone": "", "notes": ""}
    data.update(overrides)
    return staff.post("/clients/new/", data)


def test_only_platform_staff_get_in(tenant_a):
    anonymous = Client(HTTP_HOST=HOST)
    response = anonymous.get("/clients/")
    assert response.status_code == 302 and response["Location"].startswith("/login/")

    owner = Client(HTTP_HOST=HOST)
    owner.cookies["django_language"] = "en"
    page = owner.post("/login/", {"username": "owner@alpha.test", "password": PASSWORD})
    assert page.status_code == 200  # refused: a client's login is not platform staff
    assert owner.get("/").status_code == 302

    # The console does not exist on a client's host.
    assert login(tenant_a).get("/clients/").status_code == 404


def test_every_console_page_opens(staff, tenant_a):
    plan = Plan.objects.get(code="standard")
    for url in ("/", "/clients/", "/clients/?q=alp&status=active", "/clients/new/",
                f"/clients/{tenant_a.pk}/", f"/clients/{tenant_a.pk}/traffic/", "/traffic/",
                "/jobs/", "/jobs/?view=all", "/plans/", "/plans/new/", f"/plans/{plan.pk}/",
                f"/plans/{plan.pk}/delete/", "/features/", "/settings/", "/activity/",
                f"/activity/?tenant={tenant_a.pk}"):
        response = staff.get(url)
        assert response.status_code == 200, url
    for url in ("/traffic/live/", f"/clients/{tenant_a.pk}/traffic/live/"):
        parts = json.loads(staff.get(url).content)["parts"]
        assert parts["tiles"] and parts["chart"]


def test_signing_a_client_up(staff):
    Plan.objects.filter(code="standard").update(trial_days=14)
    response = _new_client(staff)
    tenant = Tenant.objects.get(slug="nile")
    assert response.status_code == 302 and response["Location"] == f"/clients/{tenant.pk}/"
    assert tenant.status == TenantStatus.ACTIVE and tenant.name == "Nile Foods"
    assert tenant.trial_ends_on == timezone.localdate() + timedelta(days=14)
    assert tenant.contact_name == "Samir"
    assert tenant.domains.get().domain == "nile.localhost"
    assert PlatformEvent.objects.filter(tenant=tenant, action="tenant.created").exists()

    # The owner signs in on the client's own address, and its data is its own.
    workspace = login(tenant, "samir", password="Nile-Owner-2026")
    assert workspace.get("/").status_code == 200
    with tenant_context(tenant.id):
        from apps.org.models import Branch, TenantProfile

        assert TenantProfile.objects.get().timezone == "Africa/Cairo"
        assert Branch.objects.get().is_head_office

    page = staff.get(f"/clients/{tenant.pk}/").content.decode()
    assert "Nile Foods" in page and "@samir" in page and "Payslips (30 days)" in page


def test_sign_up_refuses_a_taken_or_reserved_address_and_a_staff_owner(staff, tenant_a):
    for slug in ("alpha", "admin"):
        response = _new_client(staff, slug=slug)
        assert response.status_code == 200
        assert response.context["form"].errors["slug"]
    response = _new_client(staff, owner_email="ops@platform.test")
    assert "owner_email" in response.context["form"].errors
    response = _new_client(staff, owner_password="")
    assert "owner_password" in response.context["form"].errors
    assert not Tenant.objects.filter(slug="nile").exists()


def test_suspending_stops_the_workspace_the_app_and_devices(staff, tenant_a):
    workspace = login(tenant_a)
    response = staff.post(f"/clients/{tenant_a.pk}/status/", {"status": "suspended"})
    assert response.status_code == 302
    tenant_a.refresh_from_db()
    assert tenant_a.status == TenantStatus.SUSPENDED
    host = {"HTTP_HOST": "alpha.localhost"}
    assert workspace.get("/").status_code == 403
    assert Client().post("/api/v1/auth/login", {"username": "owner", "password": PASSWORD},
                         **host).status_code == 403
    assert Client().get("/iclock/cdata?SN=ABC123&options=all", **host).status_code == 403
    event = PlatformEvent.objects.get(tenant=tenant_a, action="tenant.status")
    assert event.detail == {"before": "active", "after": "suspended"}

    # Archiving needs a suspended client; an active one cannot jump there.
    staff.post(f"/clients/{tenant_a.pk}/status/", {"status": "active"})
    tenant_a.refresh_from_db()
    assert tenant_a.status == TenantStatus.ACTIVE
    assert login(tenant_a).get("/").status_code == 200
    staff.post(f"/clients/{tenant_a.pk}/status/", {"status": "archived"})
    tenant_a.refresh_from_db()
    assert tenant_a.status == TenantStatus.ACTIVE


def test_the_traffic_switch_disables_and_enables(staff, tenant_a):
    response = staff.post(f"/clients/{tenant_a.pk}/access/", {"enabled": "0"},
                          HTTP_ACCEPT="application/json")
    assert json.loads(response.content)["status"] == "suspended"
    staff.post(f"/clients/{tenant_a.pk}/access/", {"enabled": "1"})
    tenant_a.refresh_from_db()
    assert tenant_a.status == TenantStatus.ACTIVE


def test_limits_from_the_client_page_apply_in_the_workspace(staff, tenant_a, make_member):
    from apps.iam import services as iam

    Plan.objects.filter(code="standard").update(max_users=50)
    page = staff.get(f"/clients/{tenant_a.pk}/").content.decode()
    assert "/ 50" in page  # the plan's limit is the one in effect

    response = staff.post(f"/clients/{tenant_a.pk}/settings/", {
        "name": "Alpha Ltd", "plan": "standard", "max_users": "2", "max_branches": "",
        "trial_ends_on": "", "contact_name": "", "contact_email": "", "contact_phone": "",
        "notes": ""})
    assert response.status_code == 302
    tenant_a.refresh_from_db()
    assert tenant_a.name == "Alpha Ltd" and tenant_a.user_limit == 2
    make_member(tenant_a, "clerk")
    with tenant_context(tenant_a.id), pytest.raises(DomainError) as refused:
        iam.create_member(_office_member("third"), PASSWORD)
    assert refused.value.code == "PLAN_USER_LIMIT"
    event = PlatformEvent.objects.get(tenant=tenant_a, action="tenant.updated")
    assert event.detail == {"name": "Alpha Ltd", "max_users": "2"}


def _office_member(username):
    from apps.iam import services as iam
    from apps.iam.models import Role

    return iam.MemberInput(username=username, display_name=username.title(), roles=(
        iam.RoleAssignmentInput(Role.objects.get(code="viewer").pk),))


def test_app_logins_have_a_limit_of_their_own(staff, tenant_a, make_employee):
    from apps.iam import services as iam
    from apps.iam.models import MembershipStatus, Role
    from apps.mobile.access import give_login, take_login

    tenant_a.max_users, tenant_a.max_app_logins = 1, 2  # the owner fills the office place
    tenant_a.save()
    first, second, third = (make_employee(tenant_a, code) for code in (1, 2, 3))
    with tenant_context(tenant_a.id):
        # App logins do not take an office user's place…
        give_login(first.pk, "emp1", PASSWORD)
        member = give_login(second.pk, "emp2", PASSWORD)
        # …and stop at their own limit.
        with pytest.raises(DomainError) as refused:
            give_login(third.pk, "emp3", PASSWORD)
        assert refused.value.code == "PLAN_APP_LOGIN_LIMIT"
        with pytest.raises(DomainError) as refused:
            iam.create_member(_office_member("clerk"), PASSWORD)
        assert refused.value.code == "PLAN_USER_LIMIT"

        # A suspended login frees its place; coming back needs one again.
        take_login(second.pk)
        give_login(third.pk, "emp3", PASSWORD)
        with pytest.raises(DomainError) as refused:
            iam.set_member_status(member.pk, MembershipStatus.ACTIVE)
        assert refused.value.code == "PLAN_APP_LOGIN_LIMIT"

        # Turning an app login into an office user needs an office user's place.
        login_member = third.__class__.objects.get(pk=first.pk).member
        viewer = Role.objects.get(code="viewer")
        with pytest.raises(DomainError) as refused:
            iam.update_member(login_member.pk, iam.MemberInput(
                username="emp1", display_name="Employee 1",
                roles=(iam.RoleAssignmentInput(viewer.pk),)))
        assert refused.value.code == "PLAN_USER_LIMIT"

    page = staff.get(f"/clients/{tenant_a.pk}/").content.decode()
    assert "App logins" in page
    from apps.platform.console import metrics

    usage = metrics.tenant_usage(tenant_a)
    assert (usage.users, usage.app_logins) == (1, 2)


def test_the_plan_sets_the_app_login_limit(tenant_a, make_employee):
    from apps.mobile.access import give_login

    Plan.objects.filter(code="standard").update(max_app_logins=0)
    tenant_a.refresh_from_db()
    assert tenant_a.app_login_limit == 0
    employee = make_employee(tenant_a, 1)
    with tenant_context(tenant_a.id), pytest.raises(DomainError) as refused:
        give_login(employee.pk, "emp1", PASSWORD)
    assert refused.value.code == "PLAN_APP_LOGIN_LIMIT"
    tenant_a.max_app_logins = 1  # the client's own limit wins
    tenant_a.save()
    with tenant_context(tenant_a.id):
        give_login(employee.pk, "emp1", PASSWORD)


def test_company_settings_are_saved_in_the_clients_own_data(staff, tenant_a):
    from apps.org.models import TenantProfile

    response = staff.post(f"/clients/{tenant_a.pk}/profile/", {
        "display_name": "Alpha Co.", "locale": "en", "country": "SA",
        "timezone": "Asia/Riyadh", "accent": "teal"})
    assert response.status_code == 302
    with tenant_context(tenant_a.id):
        profile = TenantProfile.objects.get()
    assert (profile.display_name, profile.locale, profile.country, profile.timezone) == (
        "Alpha Co.", "en", "SA", "Asia/Riyadh")


def test_addresses(staff, tenant_a):
    staff.post(f"/clients/{tenant_a.pk}/domains/", {"domain": "HR.Alpha-Co.localhost."})
    added = TenantDomain.objects.get(domain="hr.alpha-co.localhost")
    assert Client(HTTP_HOST="hr.alpha-co.localhost").get("/login/").status_code == 200
    # A domain of the client's own opens at once: no settings change, no restart.
    stranger = Client(HTTP_HOST="hr.alpha.example")
    assert stranger.get("/login/").status_code == 400  # not a client's yet
    staff.post(f"/clients/{tenant_a.pk}/domains/", {"domain": "hr.alpha.example"})
    assert Client(HTTP_HOST="hr.alpha.example").get("/login/").status_code == 200
    staff.post(f"/clients/{tenant_a.pk}/domains/", {"domain": "admin.localhost"})
    assert not TenantDomain.objects.filter(domain="admin.localhost").exists()

    primary = tenant_a.domains.get(is_primary=True)
    staff.post(f"/clients/{tenant_a.pk}/domains/{primary.pk}/remove/")
    assert TenantDomain.objects.filter(pk=primary.pk).exists()
    staff.post(f"/clients/{tenant_a.pk}/domains/{added.pk}/remove/")
    assert not TenantDomain.objects.filter(pk=added.pk).exists()
    # Gone: the fixed .localhost pattern still lets the host in, but no client answers.
    assert Client(HTTP_HOST="hr.alpha-co.localhost").get("/login/").status_code == 404


def test_unknown_hosts_are_refused(tenant_a):
    for host in ("evil.example", "alpha.localhost.evil.example", "bad host"):
        assert Client(HTTP_HOST=host).get("/login/").status_code == 400, host
    assert Client(HTTP_HOST="alpha.localhost").get("/login/").status_code == 200
    assert Client(HTTP_HOST="admin.localhost").get("/login/").status_code == 200


def test_the_web_server_asks_before_an_https_certificate(tenant_a, tenant_b):
    ask = Client(HTTP_HOST=HOST)
    TenantDomain.objects.create(tenant=tenant_a, domain="hr.alpha.example")
    assert ask.get("/tls/allowed/?domain=hr.alpha.example").status_code == 200
    assert ask.get("/tls/allowed/?domain=alpha.localhost").status_code == 200
    assert ask.get("/tls/allowed/?domain=admin.localhost").status_code == 200
    # A pattern host (.localhost) is not enough: only real client domains get certificates.
    assert ask.get("/tls/allowed/?domain=made-up.localhost").status_code == 404
    assert ask.get("/tls/allowed/?domain=").status_code == 404
    tenant_b.status = TenantStatus.ARCHIVED
    tenant_b.save()
    assert ask.get("/tls/allowed/?domain=bravo.localhost").status_code == 404


def test_features_for_a_client_and_for_a_plan(staff, tenant_a, tenant_b):
    staff.post(f"/clients/{tenant_a.pk}/features/", {"key": "attendance", "state": "off"})
    assert not features.is_enabled(tenant_a.pk, "attendance")
    assert not features.is_enabled(tenant_a.pk, "overtime")  # needs attendance
    assert features.is_enabled(tenant_b.pk, "attendance")
    assert login(tenant_a).get("/attendance/").status_code in (403, 404)

    page = staff.get(f"/clients/{tenant_a.pk}/").content.decode()
    assert "Off until this is on:" in page

    staff.post(f"/clients/{tenant_a.pk}/features/", {"key": "attendance", "state": "default"})
    assert not TenantFeature.objects.filter(tenant=tenant_a).exists()
    assert features.is_enabled(tenant_a.pk, "attendance")

    staff.post("/features/plan/", {"plan": "standard", "key": "evaluations", "enabled": "0"})
    assert PlanFeature.objects.get(plan="standard", key="evaluations").enabled is False
    assert not features.is_enabled(tenant_a.pk, "evaluations")
    assert not features.is_enabled(tenant_b.pk, "evaluations")
    assert PlatformEvent.objects.filter(action="feature.plan").exists()

    # Unknown features or states are refused rather than saved.
    assert staff.post(f"/clients/{tenant_a.pk}/features/",
                      {"key": "nope", "state": "on"}).status_code == 404


def test_plans_created_edited_and_deleted_with_their_clients_moved(staff, tenant_a):
    data = {"code": "small", "name": "Small", "name_ar": "صغيرة", "description": "",
            "price": "500", "currency": "EGP", "billing_period": "monthly",
            "max_branches": "1", "max_users": "5", "requests_per_minute": "",
            "trial_days": "7", "position": "9", "is_active": "on"}
    data.update({f"feature_{f.key}": "on" for f in features.FEATURES if f.key != "loans"})
    assert staff.post("/plans/new/", data).status_code == 302
    small = Plan.objects.get(code="small")
    assert small.max_users == 5
    assert features.plan_defaults()["small"]["loans"] is False

    tenant_a.plan = small
    tenant_a.save()
    assert not features.is_enabled(tenant_a.pk, "loans")

    response = staff.post(f"/plans/{small.pk}/delete/", {"move_to": "standard"})
    assert response.status_code == 302
    tenant_a.refresh_from_db()
    assert tenant_a.plan_id == "standard" and not Plan.objects.filter(code="small").exists()
    assert PlatformEvent.objects.filter(action="plan.deleted").exists()


def test_jobs_run_again_or_cancelled(staff, tenant_a):
    from apps.platform.jobs.models import Job, JobStatus

    failed = Job.objects.create(name="messaging.send", tenant=tenant_a, status=JobStatus.FAILED,
                                attempts=5, max_attempts=5, last_error="gateway down")
    waiting = Job.objects.create(name="messaging.send", tenant=tenant_a)
    assert "gateway down" in staff.get("/jobs/").content.decode()
    staff.post(f"/jobs/{failed.pk}/retry/")
    failed.refresh_from_db()
    assert failed.status == JobStatus.QUEUED and failed.max_attempts == 6
    staff.post(f"/jobs/{waiting.pk}/cancel/")
    waiting.refresh_from_db()
    assert waiting.status == JobStatus.CANCELLED


def test_the_overview_counts_each_client_in_its_own_data(staff, tenant_a, tenant_b,
                                                         make_employee):
    from apps.platform.console import metrics

    make_employee(tenant_a, 1)
    make_employee(tenant_a, 2)
    make_employee(tenant_b, 1)
    data = metrics.overview()
    by_slug = {u.tenant.slug: u for u in data.tenants}
    assert by_slug["alpha"].employees == 2 and by_slug["bravo"].employees == 1
    assert data.employees == 3 and data.users == 2
    assert by_slug["alpha"].health == "active"  # the employees were just saved
    assert sum(by_slug["alpha"].daily.values()) >= 2 and len(data.daily["marks"]) == 14
    assert staff.get("/").status_code == 200
