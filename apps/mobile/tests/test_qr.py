"""Signing in to the app by QR: a one-time code in place of an address and a password, from a
manager who may do it; and one phone signed out at once, without touching the others."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.errors import DomainError, NotFound, PermissionDenied
from apps.core.tenancy import tenant_context
from apps.employees.models import Employee
from apps.iam.authz import build_actor
from apps.iam.models import MembershipStatus
from apps.mobile.models import AppDevice, AppLinkCode, BiometricEnrollment
from apps.mobile.tests.test_contract import App, _switch
from apps.org.models import TenantProfile
from conftest import PASSWORD, login

from ..services import access, devices, qr

pytestmark = pytest.mark.django_db


@pytest.fixture
def sara(tenant_a, make_employee):
    _switch(tenant_a)
    return make_employee(tenant_a, 7, name="Sara Adel")


def _issue(tenant, employee, actor=None):
    with tenant_context(tenant.id):
        return qr.issue(employee.pk, actor=actor)


def _scan(tenant, code, device="phone-1"):
    phone = App(tenant)
    response = phone.post("auth/qr", {"code": code, "device_id": device})
    if response.status_code == 200:
        phone.token = response.json()["access"]
    return phone, response


def test_scanning_signs_in_like_a_login_and_only_once(tenant_a, sara):
    issued = _issue(tenant_a, sara)

    phone, response = _scan(tenant_a, issued.code)

    assert response.status_code == 200
    body = response.json()
    assert {"access", "refresh", "username", "role", "is_superuser", "employee"} <= set(body)
    assert body["employee"]["name"] == "Sara Adel"
    assert phone.get("me").status_code == 200

    again = _scan(tenant_a, issued.code, "phone-2")[1]
    assert (again.status_code, again.json()["code"]) == (400, "qr_used")


def test_the_employee_gets_a_login_nobody_knows_the_password_of(tenant_a, sara):
    _issue(tenant_a, sara)
    with tenant_context(tenant_a.id):
        member = Employee.objects.get(pk=sara.pk).member
        assert member.username == "emp7"
        assert member.user.has_usable_password()


def test_the_code_is_not_kept_and_not_in_the_history(tenant_a, sara):
    issued = _issue(tenant_a, sara)
    with tenant_context(tenant_a.id):
        link = AppLinkCode.objects.get()
        assert link.code_hash != issued.code and issued.code not in link.code_hash
        events = AuditEvent.objects.filter(table_name="mobile_applinkcode")
        assert events.exists()
        assert not any("code_hash" in event.changes for event in events)


def test_the_payload_is_the_address_and_the_code_only(tenant_a, sara):
    issued = _issue(tenant_a, sara)
    text = qr.link_text("https://acme.example.com", issued.code)
    parts = urlparse(text)
    assert (parts.scheme, parts.netloc) == ("payroll", "link")
    assert parse_qs(parts.query) == {"url": ["https://acme.example.com"], "code": [issued.code]}
    assert qr.qr_svg(text).startswith("<svg")


def test_a_code_expires_with_the_companys_setting(tenant_a, sara):
    with tenant_context(tenant_a.id):
        TenantProfile.objects.update(app_qr_minutes=120)
    issued = _issue(tenant_a, sara)
    left = issued.link.expires_at - timezone.now()
    assert timedelta(minutes=119) < left <= timedelta(minutes=120)

    with tenant_context(tenant_a.id):
        AppLinkCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = _scan(tenant_a, issued.code)[1]
    assert response.json()["code"] == "qr_expired"


def test_a_new_one_replaces_the_old_and_renewing_keeps_it(tenant_a, sara):
    first = _issue(tenant_a, sara)
    second = _issue(tenant_a, sara)
    assert _scan(tenant_a, first.code)[1].json()["code"] == "qr_invalid"

    with tenant_context(tenant_a.id):
        AppLinkCode.objects.filter(pk=second.link.pk).update(
            expires_at=timezone.now() + timedelta(seconds=30))
        renewed = qr.renew(sara.pk)
    assert renewed.pk == second.link.pk
    assert renewed.expires_at - timezone.now() > timedelta(minutes=14)
    assert _scan(tenant_a, second.code)[1].status_code == 200


def test_a_cancelled_code_stops_working(tenant_a, sara):
    issued = _issue(tenant_a, sara)
    with tenant_context(tenant_a.id):
        assert qr.cancel(sara.pk) == 1
    assert _scan(tenant_a, issued.code)[1].json()["code"] == "qr_invalid"


def test_a_code_works_only_on_its_own_client(tenant_a, tenant_b, sara):
    issued = _issue(tenant_a, sara)
    _switch(tenant_b)
    assert _scan(tenant_b, issued.code)[1].json()["code"] == "qr_invalid"


def test_a_login_suspended_after_the_qr_refuses_it(tenant_a, sara):
    issued = _issue(tenant_a, sara)
    with tenant_context(tenant_a.id):
        Employee.objects.get(pk=sara.pk).member.__class__.objects.update(
            status=MembershipStatus.SUSPENDED)
    assert _scan(tenant_a, issued.code)[1].json()["code"] == "qr_invalid"


def test_a_login_taken_away_after_the_qr_refuses_it(tenant_a, sara):
    issued = _issue(tenant_a, sara)
    with tenant_context(tenant_a.id):
        access.take_login(sara.pk)
    assert _scan(tenant_a, issued.code)[1].json()["code"] == "qr_invalid"


def test_guessing_is_locked_but_old_qrs_scanned_by_mistake_are_not(tenant_a, sara):
    issued = _issue(tenant_a, sara)
    assert _scan(tenant_a, issued.code)[1].status_code == 200
    for _ in range(8):
        assert _scan(tenant_a, issued.code)[1].json()["code"] == "qr_used"

    for _ in range(5):
        assert _scan(tenant_a, "guess")[1].json()["code"] == "qr_invalid"
    locked = _scan(tenant_a, "guess")[1]
    assert (locked.status_code, locked.json()["code"]) == (429, "qr_locked")


def test_who_may_give_a_qr(tenant_a, sara, make_member):
    with tenant_context(tenant_a.id):
        manager = build_actor(make_member(tenant_a, "mgr", "manager"))
        viewer = build_actor(make_member(tenant_a, "view", "viewer"))
    assert _issue(tenant_a, sara, manager).code
    with pytest.raises(NotFound), tenant_context(tenant_a.id):
        qr.issue(sara.pk, actor=viewer)


def test_a_manager_cant_get_into_a_login_above_their_own(tenant_a, sara, make_member):
    with tenant_context(tenant_a.id):
        owner_member = make_member(tenant_a, "boss", "owner")
        manager = build_actor(make_member(tenant_a, "mgr", "manager"))
        Employee.objects.filter(pk=sara.pk).update(member=owner_member)
        with pytest.raises(PermissionDenied):
            qr.issue(sara.pk, actor=manager)
        assert not AppLinkCode.objects.exists()


def test_a_user_whose_role_has_no_app_cant_get_a_qr(tenant_a, sara, make_member):
    with tenant_context(tenant_a.id):
        viewer = make_member(tenant_a, "view", "viewer")
        Employee.objects.filter(pk=sara.pk).update(member=viewer)
        with pytest.raises(DomainError):
            qr.issue(sara.pk)


def test_someone_who_left_cant_get_a_qr(tenant_a, sara):
    with tenant_context(tenant_a.id):
        Employee.objects.filter(pk=sara.pk).update(
            left_on=timezone.localdate() - timedelta(days=1), hired_on="2020-01-01")
        with pytest.raises(DomainError):
            qr.issue(sara.pk)


def test_signing_one_phone_out_takes_effect_at_once(tenant_a, sara):
    first, second = _issue(tenant_a, sara), None
    phone, response = _scan(tenant_a, first.code, "phone-1")
    refresh = response.json()["refresh"]
    second = _issue(tenant_a, sara)
    other = _scan(tenant_a, second.code, "phone-2")[0]
    with tenant_context(tenant_a.id):
        device = AppDevice.objects.get(device_id="phone-1")
        BiometricEnrollment.objects.create(
            employee=Employee.objects.get(pk=sara.pk), device_id="phone-1",
            secret_encrypted="x", app_version="1")
        devices.revoke(device.pk)
        assert not BiometricEnrollment.objects.get().is_active

    assert phone.get("me").status_code == 401
    assert phone.post("auth/refresh", {"refresh": refresh}).status_code == 401
    assert other.get("me").status_code == 200


def test_scanning_again_lets_a_signed_out_phone_back_in(tenant_a, sara):
    phone, _response = _scan(tenant_a, _issue(tenant_a, sara).code)
    with tenant_context(tenant_a.id):
        devices.revoke(AppDevice.objects.get().pk)
    phone, response = _scan(tenant_a, _issue(tenant_a, sara).code)
    assert response.status_code == 200
    assert phone.get("me").status_code == 200


def test_a_password_sign_in_names_its_phone_and_an_older_app_still_works(tenant_a, sara):
    with tenant_context(tenant_a.id):
        access.give_login(sara.pk, "sara", PASSWORD)

    older = App(tenant_a)
    assert older.sign_in("sara").status_code == 200
    assert older.get("me").status_code == 200
    with tenant_context(tenant_a.id):
        assert not AppDevice.objects.exists()

    newer = App(tenant_a)
    assert newer.post("auth/login", {"username": "sara", "password": PASSWORD,
                                     "device_id": "phone-1"}).status_code == 200
    with tenant_context(tenant_a.id):
        assert AppDevice.objects.get().method == "password"


def test_the_employees_page_gives_and_shows_a_qr(tenant_a, sara):
    owner = login(tenant_a, language="en")
    page = reverse("employee", args=[sara.pk])
    url = reverse("app-qr-detail", args=[sara.pk])

    assert "data-app-qr" in owner.get(page).content.decode()
    made = owner.put(url, {}, content_type="application/json")
    assert made.status_code == 200
    assert made.json()["svg"].startswith("<svg")
    assert "Generate a new QR" in owner.get(page).content.decode()

    assert owner.post(f"{url}renew/", {}, content_type="application/json").status_code == 200
    assert owner.delete(url).status_code == 204


def test_the_card_is_for_those_who_may_use_it(tenant_a, sara, make_member):
    make_member(tenant_a, "view", "viewer")
    viewer = login(tenant_a, "view", language="en")
    assert "data-app-qr" not in viewer.get(reverse("employee", args=[sara.pk])).content.decode()
    assert viewer.put(reverse("app-qr-detail", args=[sara.pk]), {},
                      content_type="application/json").status_code == 403


def test_the_time_is_set_on_the_company_page(tenant_a, sara):
    owner = login(tenant_a, language="en")
    with tenant_context(tenant_a.id):
        profile = TenantProfile.objects.get()
    url = reverse("company")
    assert 'name="app_qr_minutes"' in owner.get(url).content.decode()

    body = {"display_name": profile.display_name, "accent": profile.accent}
    assert b"Ensure this value" in owner.post(url, {**body, "app_qr_minutes": 20000}).content
    owner.post(url, {**body, "app_qr_minutes": 45})
    with tenant_context(tenant_a.id):
        assert TenantProfile.objects.get().app_qr_minutes == 45
