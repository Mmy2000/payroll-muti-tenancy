"""Features switched on and off per client and per plan by the platform admin."""

import pytest
from django.test import Client

from apps.iam.models import User
from apps.platform.tenants import features
from apps.platform.tenants.features import Feature
from apps.platform.tenants.models import PlanFeature, PlatformEvent, TenantFeature
from conftest import PASSWORD, login

pytestmark = pytest.mark.django_db


@pytest.fixture
def registered(monkeypatch):
    """Features owning phase 0's own screens (the audit trail and sign-in history), so switching
    them is visible; plus a chain where `overtime` needs `attendance`."""
    registry, by_key = [], {}
    monkeypatch.setattr(features, "FEATURES", registry)
    monkeypatch.setattr(features, "BY_KEY", by_key)
    for feature in (
        Feature("history", "History", "", features.TOOLS, "history", ("admin.audit.",)),
        Feature("sign_ins", "Sign-ins", "", features.TOOLS, "log-in", ("admin.signins.",),
                default=False),
        Feature("attendance", "Attendance", "", features.ATTENDANCE, "clock", ()),
        Feature("overtime", "Overtime", "", features.ATTENDANCE, "timer", (),
                requires=("attendance",)),
    ):
        features.register_feature(feature)
    return by_key


@pytest.fixture
def admin_client(db):
    User.objects.create_superuser(email="ops@platform.test", password=PASSWORD,
                                  display_name="Ops")
    client = Client(HTTP_HOST="admin.localhost")
    client.cookies["django_language"] = "en"
    assert client.post("/django-admin/login/", {"username": "ops@platform.test",
                                                "password": PASSWORD}).status_code == 302
    return client


def _workspace(tenant):
    client = login(tenant)
    client.cookies["django_language"] = "en"
    return client


def _switch(tenant, key, enabled):
    TenantFeature.objects.update_or_create(tenant=tenant, key=key,
                                           defaults={"enabled": enabled})
    features.forget(tenant.pk)


def test_a_feature_cannot_be_registered_twice(registered):
    with pytest.raises(ValueError):
        features.register_feature(Feature("history", "Again", "", features.TOOLS, "x", ()))


def test_defaults_apply_until_something_is_chosen(registered, tenant_a):
    assert features.enabled_keys(tenant_a.pk) == {"history", "attendance", "overtime"}
    html = _workspace(tenant_a).get("/").content.decode()
    assert 'href="/settings/activity/"' in html
    assert 'href="/settings/sign-ins/"' not in html  # off by default


def test_switching_a_feature_off_for_one_client(registered, tenant_a, tenant_b):
    _switch(tenant_a, "history", False)

    owner = _workspace(tenant_a)  # the Owner (every permission) loses it too
    assert 'href="/settings/activity/"' not in owner.get("/").content.decode()
    page = owner.get("/settings/activity/")
    assert page.status_code == 403 and "not in your plan" in page.content.decode()
    # Everything else still works, and another client is untouched.
    assert owner.get("/branches/").status_code == 200
    assert _workspace(tenant_b).get("/settings/activity/").status_code == 200

    TenantFeature.objects.filter(tenant=tenant_a).delete()
    features.forget(tenant_a.pk)
    assert _workspace(tenant_a).get("/settings/activity/").status_code == 200


def test_a_feature_needs_the_features_it_requires(registered, tenant_a):
    _switch(tenant_a, "attendance", False)
    assert not features.is_enabled(tenant_a.pk, "overtime")
    state = {s.feature.key: s for s in features.states(tenant_a)}["overtime"]
    assert state.chosen and not state.enabled
    assert [f.key for f in state.blocked_by] == ["attendance"]

    _switch(tenant_a, "attendance", True)
    assert features.is_enabled(tenant_a.pk, "overtime")


def test_effective_refuses_unknown_requirements_and_cycles(registered):
    features.register_feature(Feature("a", "A", "", features.PAY, "x", (), requires=("b",)))
    features.register_feature(Feature("b", "B", "", features.PAY, "x", (), requires=("a",)))
    features.register_feature(Feature("c", "C", "", features.PAY, "x", (), requires=("nope",)))
    on = features.effective({})
    assert not on["a"] and not on["b"] and not on["c"] and on["attendance"]


def test_plan_defaults_and_client_exceptions(registered, tenant_a, tenant_b):
    tenant_b.plan_id = "enterprise"
    tenant_b.save()
    PlanFeature.objects.create(plan_id=tenant_a.plan_id, key="history", enabled=False)
    features.forget()
    assert not features.is_enabled(tenant_a.pk, "history")
    assert features.is_enabled(tenant_b.pk, "history")  # another plan

    # A client-level "on" beats the plan.
    _switch(tenant_a, "history", True)
    assert features.is_enabled(tenant_a.pk, "history")


def test_the_platform_admin_switches_features(registered, admin_client, tenant_a):
    page = admin_client.get(f"/django-admin/tenants/tenant/{tenant_a.pk}/change/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Features in effect" in html and "History" in html

    data = {
        "slug": tenant_a.slug, "name": tenant_a.name, "status": tenant_a.status,
        "plan": tenant_a.plan_id, "domains-TOTAL_FORMS": "0", "domains-INITIAL_FORMS": "0",
        "features-TOTAL_FORMS": "1", "features-INITIAL_FORMS": "0",
        "features-0-key": "history", "features-0-enabled": "",
    }
    for domain in tenant_a.domains.all():
        index = int(data["domains-TOTAL_FORMS"])
        data.update({f"domains-{index}-id": domain.pk, f"domains-{index}-tenant": tenant_a.pk,
                     f"domains-{index}-domain": domain.domain,
                     f"domains-{index}-is_primary": "on" if domain.is_primary else ""})
        data["domains-TOTAL_FORMS"] = data["domains-INITIAL_FORMS"] = str(index + 1)
    response = admin_client.post(f"/django-admin/tenants/tenant/{tenant_a.pk}/change/", data)
    assert response.status_code == 302, response.content.decode()[:2000]
    assert not features.is_enabled(tenant_a.pk, "history")
    assert PlatformEvent.objects.filter(tenant=tenant_a, action="feature.client").exists()
    assert _workspace(tenant_a).get("/settings/activity/").status_code == 403


def test_only_platform_staff_reach_the_feature_switches(registered, tenant_a):
    # A client's Owner has no way in: the admin does not exist on tenant hosts…
    assert _workspace(tenant_a).get("/django-admin/").status_code == 404
    # …and a client login is not platform staff.
    client = Client(HTTP_HOST="admin.localhost")
    client.post("/django-admin/login/", {"username": "owner@alpha.test", "password": PASSWORD})
    assert client.get(f"/django-admin/tenants/tenant/{tenant_a.pk}/change/").status_code == 302


def test_every_feature_owns_real_permissions_and_none_overlap():
    from apps.iam.catalog import permissions

    codes = list(permissions())
    for feature in features.FEATURES:
        for prefix in feature.permissions:
            assert any(code == prefix or code.startswith(prefix) for code in codes), (
                f"{feature.key}: no permission matches {prefix!r}")
        for required in feature.requires:
            assert required in features.BY_KEY, f"{feature.key} requires unknown {required!r}"
    for code in codes:
        owning = [f.key for f in features.FEATURES if f.owns(code)]
        assert len(owning) <= 1, f"{code} belongs to {owning}"
    assert len({f.key for f in features.FEATURES}) == len(features.FEATURES)
