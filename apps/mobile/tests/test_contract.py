"""The mobile app's API answers as PayRole's did (docs/mobile-api.md): paths, shapes, codes and
messages, on this system's records."""

import hashlib
import hmac
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.utils import timezone

from apps.attendance.leave import decide_leave
from apps.attendance.models import LeaveRequest, Punch, PunchSource
from apps.core.tenancy import tenant_context
from apps.mobile import access
from apps.mobile.models import TrackSession
from apps.notifications.models import Notification
from apps.org.models import Branch
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from conftest import PASSWORD

pytestmark = pytest.mark.django_db
CAIRO = ZoneInfo("Africa/Cairo")


def _switch(tenant, **keys):
    for key, enabled in {"mobile_app": True, **keys}.items():
        TenantFeature.objects.update_or_create(tenant=tenant, key=key,
                                               defaults={"enabled": enabled})
    features.forget(tenant.pk)


class App:
    """The phone: JSON to the client's host, with its bearer token once signed in."""

    def __init__(self, tenant):
        self.client = Client(HTTP_HOST=f"{tenant.slug}.localhost")
        self.token = None

    def _headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"} if self.token else {}

    def get(self, path, **query):
        return self.client.get(f"/api/v1/{path}", query, **self._headers())

    def post(self, path, body=None):
        return self.client.post(f"/api/v1/{path}", body or {}, content_type="application/json",
                                **self._headers())

    def patch(self, path, body):
        return self.client.patch(f"/api/v1/{path}", body, content_type="application/json",
                                 **self._headers())

    def delete(self, path):
        return self.client.delete(f"/api/v1/{path}", **self._headers())

    def sign_in(self, username="mona", password=PASSWORD):
        response = self.post("auth/login", {"username": username, "password": password})
        if response.status_code == 200:
            self.token = response.json()["access"]
        return response


@pytest.fixture
def mona(tenant_a, make_employee):
    _switch(tenant_a)
    employee = make_employee(tenant_a, 7, name="Mona Adel", annual_leave_days=21)
    with tenant_context(tenant_a.id):
        access.give_login(employee.pk, "mona", PASSWORD)
    return employee


@pytest.fixture
def app(tenant_a, mona):
    phone = App(tenant_a)
    assert phone.sign_in().status_code == 200
    return phone


# --- signing in --------------------------------------------------------------------------------


def test_login_answers_as_payrole(tenant_a, mona):
    phone = App(tenant_a)
    wrong = phone.sign_in(password="nope")
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "No active account found with the given credentials"}
    assert phone.post("auth/login", {}).json() == {
        "username": ["This field is required."], "password": ["This field is required."]}
    body = phone.sign_in().json()
    assert list(body) == ["refresh", "access", "username", "role", "is_superuser", "employee"]
    assert (body["username"], body["role"], body["is_superuser"]) == ("mona", "employee", False)
    assert body["employee"] == {"eco": 7, "name": "Mona Adel", "branch_code": 1,
                                "branch_name": body["employee"]["branch_name"], "group": None,
                                "photo": None, "day_off": "fr"}


def test_tokens_refresh_verify_and_stay_with_their_client(tenant_a, tenant_b, mona):
    phone = App(tenant_a)
    tokens = phone.sign_in().json()
    refreshed = phone.post("auth/refresh", {"refresh": tokens["refresh"]})
    assert refreshed.status_code == 200 and set(refreshed.json()) == {"access", "refresh"}
    assert phone.post("auth/verify", {"token": tokens["access"]}).json() == {}
    elsewhere = App(tenant_b)
    elsewhere.token = tokens["access"]
    assert elsewhere.get("me").status_code == 401
    stolen = elsewhere.post("auth/refresh", {"refresh": tokens["refresh"]})
    assert stolen.status_code == 401 and stolen.json() == {"detail": "Token is invalid",
                                                           "code": "token_not_valid"}


def test_without_a_token_or_the_feature(tenant_a, mona):
    phone = App(tenant_a)
    missing = phone.get("me")
    assert missing.status_code == 401
    assert missing.json() == {"detail": "Authentication credentials were not provided."}
    assert missing["WWW-Authenticate"] == 'Bearer realm="api"'
    phone.token = "nonsense"
    assert phone.get("me").json()["code"] == "token_not_valid"
    assert App(tenant_a).client.get("/api/v1/me/").status_code == 404  # no trailing slash
    _switch(tenant_a, mobile_app=False)
    assert App(tenant_a).sign_in().status_code == 401  # the app is off for this client


def test_me_and_config(tenant_a, app):
    me = app.get("me").json()
    assert set(me) == {"username", "is_superuser", "employee", "leave_balance", "today",
                       "active_session", "notifications_unread"}
    assert me["leave_balance"] == {"year": timezone.localdate().year, "allowed": 21, "used": 0,
                                   "remaining": 21}
    assert app.get("config").json() == {
        "track_interval_seconds": 120, "track_distance_filter_m": 50, "track_batch_size": 10,
        "track_max_session_hours": 14, "track_retention_days": 14, "enforce_geofence": False,
        "tracking_required": False, "biometric_required": False}


def test_a_member_without_an_employee_file(tenant_a, make_member):
    from apps.iam.models import Role
    from apps.iam.services import assign_role, set_role_permissions

    _switch(tenant_a)
    clerk = make_member(tenant_a, "clerk", "viewer")
    with tenant_context(tenant_a.id):  # may use the app, may not follow routes
        role = Role.objects.create(code="app-only", name="App only")
        set_role_permissions(role, ["mobile.signin"])
        assign_role(clerk, role)
    phone = App(tenant_a)
    assert phone.sign_in("clerk").json()["employee"] is None
    assert phone.get("me").json() == {"detail": "لا يوجد ملف موظف مرتبط بهذا المستخدم",
                                      "code": "no_employee"}
    assert phone.post("attendance/punch", {"status": 0}).status_code == 400


# --- punching ----------------------------------------------------------------------------------


def test_check_in_check_out_and_duplicates(tenant_a, app, mona):
    check_in = app.post("attendance/punch", {"status": 0, "latitude": "30.044400",
                                             "longitude": "31.235700"})
    assert check_in.status_code == 201, check_in.content
    body = check_in.json()
    assert body["attendance"]["status_text"] == "حضور"
    assert body["attendance"]["latitude"] == "30.044400" and body["tracking"] is True
    again = app.post("attendance/punch", {"status": 0})
    assert again.status_code == 409 and again.json()["code"] == "duplicate"
    assert again.json()["detail"].startswith("يوجد تسجيل حضور بالفعل اليوم الساعة ")
    out = app.post("attendance/punch", {"status": 1})
    assert out.status_code == 201 and out.json()["session"]["end_reason"] == "checkout"
    today = app.get("attendance/today").json()
    assert today["check_in"]["status"] == 0 and today["check_out"]["status"] == 1
    assert today["tracking"] is False and len(app.get("attendance/history").json()) == 2
    with tenant_context(tenant_a.id):
        assert set(Punch.objects.filter(employee=mona).values_list("source", flat=True)) == {
            PunchSource.MOBILE}


def test_no_check_out_before_check_in(app):
    refused = app.post("attendance/punch", {"status": 1})
    assert refused.status_code == 400 and refused.json() == {
        "detail": "لا يمكن تسجيل الانصراف قبل تسجيل الحضور", "code": "no_check_in"}


def test_a_night_shift_checks_out_after_midnight(tenant_a, make_employee, monkeypatch):
    _switch(tenant_a)
    night = make_employee(tenant_a, 9, starts_at=time(22), ends_at=time(6))
    with tenant_context(tenant_a.id):
        access.give_login(night.pk, "guard", PASSWORD)
    phone = App(tenant_a)
    phone.sign_in("guard")
    evening = datetime(2026, 10, 5, 22, 3, tzinfo=CAIRO)
    monkeypatch.setattr(timezone, "now", lambda: evening)
    assert phone.post("attendance/punch", {"status": 0}).status_code == 201
    monkeypatch.setattr(timezone, "now", lambda: evening + timedelta(hours=8))
    morning = phone.post("attendance/punch", {"status": 1})
    assert morning.status_code == 201, morning.content  # PayRole: no_check_in


def test_the_fingerprint_proof(tenant_a, app):
    _switch(tenant_a, biometric=True)
    assert app.post("attendance/punch", {"status": 0}).json()["code"] == \
        "biometric_not_enrolled"
    enrolled = app.post("biometric/enroll", {"device_id": "pixel-8"})
    assert enrolled.status_code == 201
    secret, enrollment = enrolled.json()["secret"], enrolled.json()["enrollment_id"]
    assert len(secret) == 64
    assert app.post("attendance/punch", {"status": 0, "device_id": "pixel-8"}).json()[
        "code"] == "biometric_required"

    def proof(nonce, stamp=None):
        stamp = stamp or timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S")
        message = f"{enrollment}|pixel-8|0|{stamp}|{nonce}".encode()
        return {"enrollment_id": enrollment, "timestamp": stamp, "nonce": nonce,
                "proof": hmac.new(bytes.fromhex(secret), message, hashlib.sha256).hexdigest()}

    old = (timezone.localtime() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
    stale = app.post("attendance/punch", {"status": 0, "device_id": "pixel-8",
                                          "biometric": proof("n0", old)})
    assert stale.status_code == 403 and stale.json()["code"] == "biometric_stale"
    other = app.post("attendance/punch", {"status": 0, "device_id": "iphone",
                                          "biometric": proof("n1")})
    assert other.json()["code"] == "biometric_device_mismatch"
    good = app.post("attendance/punch", {"status": 0, "device_id": "pixel-8",
                                         "biometric": proof("n2")})
    assert good.status_code == 201, good.content
    replay = app.post("attendance/punch", {"status": 1, "device_id": "pixel-8",
                                           "biometric": proof("n2")})
    assert replay.status_code in (403, 409)  # signed for a check-in: invalid, or a replay
    assert app.get("biometric/status").json()["enrolled"] is True
    assert app.post("biometric/revoke").status_code == 204
    assert app.get("biometric/status").json()["enrolled"] is False


def test_tracking_and_the_geofence(tenant_a, app, mona):
    _switch(tenant_a, gps_tracking=True, geofence=True)
    assert app.post("attendance/punch", {"status": 0}).json()["code"] == "tracking_required"
    with tenant_context(tenant_a.id):
        Branch.objects.filter(pk=mona.branch_id).update(
            latitude=Decimal("30.044400"), longitude=Decimal("31.235700"), radius_m=150)
    far = app.post("attendance/punch", {"status": 0, "tracking_enabled": True,
                                        "latitude": "30.060000", "longitude": "31.235700"})
    assert far.status_code == 400 and far.json()["code"] == "outside_geofence"
    near = app.post("attendance/punch", {"status": 0, "tracking_enabled": True,
                                         "latitude": "30.044900", "longitude": "31.235700"})
    assert near.status_code == 201
    start = timezone.localtime().replace(tzinfo=None, microsecond=0)
    points = [{"latitude": "30.044900", "longitude": "31.235700",
               "recorded_at": (start + timedelta(minutes=i)).isoformat()} for i in range(3)]
    points[1]["latitude"] = "30.045900"
    batch = app.post("track/batch", {"points": points})
    assert batch.status_code == 200, batch.content
    assert (batch.json()["saved"], batch.json()["received"]) == (3, 3)
    again = app.post("track/batch", {"points": points}).json()
    assert again["saved"] == 0 and again["session"]["points_count"] == 3
    assert Decimal(again["session"]["total_distance_m"]) > Decimal(200)  # 111 m there and back
    stopped = app.post("track/stop").json()
    assert stopped["tracking"] is False and stopped["session"]["end_reason"] == "manual"
    closed = app.post("track/batch", {"points": points})
    assert closed.status_code == 409 and closed.json() == {
        "detail": "لا توجد جلسة تتبّع مفتوحة", "code": "no_active_session", "tracking": False}


# --- leave and notifications ---------------------------------------------------------------------


def test_leave_from_the_app(tenant_a, app, mona):
    year = timezone.localdate().year + 1
    asked = app.post("leaves", {"date1": f"{year}-03-02", "date2": f"{year}-03-03", "days": 2})
    assert asked.status_code == 201, asked.content
    body = asked.json()
    assert (body["acept"], body["status_text"], body["days"]) == (False, "بانتظار الاعتماد", 2)
    with tenant_context(tenant_a.id):  # the owner may approve: they are told
        told = Notification.objects.filter(kind="leave_request")
        assert told.count() == 1 and "Mona Adel" in told.get().title
    assert app.get("leaves/balance", year=year).json()["used"] == 2
    backwards = app.post("leaves", {"date1": f"{year}-03-05", "date2": f"{year}-03-01",
                                    "days": 1})
    assert backwards.json() == {"non_field_errors": ["تاريخ نهاية الإجازة قبل تاريخ بدايتها"]}
    too_long = app.post("leaves", {"date1": f"{year}-04-01", "date2": f"{year}-06-30",
                                   "days": 60})
    assert too_long.json()["code"] == "insufficient_balance"
    assert app.delete(f"leaves/{body['ser']}").status_code == 204
    with tenant_context(tenant_a.id):
        assert Notification.objects.filter(kind="leave_withdrawn").exists()

    second = app.post("leaves", {"date1": f"{year}-05-04", "date2": f"{year}-05-04",
                                 "days": 1}).json()
    with tenant_context(tenant_a.id):
        decide_leave(second["ser"], "approve")
    listed = app.get("leaves", year=year).json()
    assert [row["acept"] for row in listed] == [True]
    assert app.delete(f"leaves/{second['ser']}").json()["code"] == "already_accepted"
    news = app.get("notifications").json()
    assert news["unread"] >= 1 and news["items"][0]["kind"] == "leave_approved"
    assert app.post("notifications/read").json()["unread"] == 0


# --- the profile and the password ----------------------------------------------------------------


def test_profile_and_password(tenant_a, app):
    profile = app.get("profile").json()
    assert profile["eco"] == 7 and profile["annual_leave"] == 21
    changed = app.patch("profile", {"tel": "01001234567", "add": "Nasr City"}).json()
    assert (changed["tel"], changed["add"]) == ("+201001234567", "Nasr City")
    assert app.patch("profile", {"tel": "abc"}).json() == {"tel": ["رقم هاتف غير صالح"]}
    assert app.patch("profile", {}).json()["code"] == "nothing_to_update"
    pixel = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42"
             "mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    assert app.patch("profile", {"image_base64": pixel}).json()["photo"].startswith("http://")

    differ = app.post("auth/change-password", {"current_password": PASSWORD,
                                               "new_password": "a-new-secret-1",
                                               "confirm_password": "something-else"})
    assert differ.json() == {"non_field_errors": ["كلمتا المرور غير متطابقتين"]}
    wrong = app.post("auth/change-password", {"current_password": "nope",
                                              "new_password": "a-new-secret-1",
                                              "confirm_password": "a-new-secret-1"})
    assert wrong.json()["code"] == "wrong_password"
    done = app.post("auth/change-password", {"current_password": PASSWORD,
                                             "new_password": "a-new-secret-1",
                                             "confirm_password": "a-new-secret-1"})
    assert done.status_code == 200 and done.json()["detail"] == "تم تغيير كلمة المرور"
    assert App(tenant_a).sign_in(password="a-new-secret-1").status_code == 200


# --- following routes ----------------------------------------------------------------------------


def test_only_route_watchers_follow_routes(tenant_a, app):
    refused = app.get("monitor/live")
    assert refused.status_code == 403
    assert refused.json() == {"detail": "متابعة المسارات متاحة للمشرف العام فقط"}
    app.post("attendance/punch", {"status": 0, "latitude": "30.044400",
                                  "longitude": "31.235700"})
    owner = App(tenant_a)
    assert owner.sign_in("owner").json()["is_superuser"] is True
    live = owner.get("monitor/live").json()
    assert live["interval_seconds"] == 120 and live["rows"][0]["position"]["source"] == "check_in"
    sessions = owner.get("monitor/sessions").json()
    assert sessions["totals"]["count"] == 1 and sessions["pages"] == 1
    with tenant_context(tenant_a.id):
        session_id = TrackSession.objects.get().pk
    detail = owner.get(f"monitor/sessions/{session_id}").json()
    assert detail["endpoints"]["check_in"]["lat"] == 30.0444
    missing = owner.get("monitor/sessions/999999")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_leave_requests_are_this_systems(tenant_a, app, mona):
    year = timezone.localdate().year + 1
    app.post("leaves", {"date1": f"{year}-03-02", "date2": f"{year}-03-02", "days": 1})
    with tenant_context(tenant_a.id):
        request = LeaveRequest.objects.get(employee=mona)
        assert request.leave_type.uses_annual_balance and request.start_date == date(year, 3, 2)


# --- from the screens ----------------------------------------------------------------------------


def test_a_login_from_the_employee_page_and_the_branch_area(tenant_a, make_employee):
    from conftest import login

    _switch(tenant_a)
    person = make_employee(tenant_a, 12, name="Hala Samir")
    owner = login(tenant_a, language="en")
    page = owner.get(f"/employees/{person.pk}/").content.decode()
    assert "Give a login to the app" in page
    given = owner.put(f"/api/web/mobile/logins/{person.pk}/",
                      {"username": "hala", "password": PASSWORD},
                      content_type="application/json")
    assert given.status_code == 200, given.content
    phone = App(tenant_a)
    assert phone.sign_in("hala").json()["employee"]["name"] == "Hala Samir"
    assert owner.delete(f"/api/web/mobile/logins/{person.pk}/").status_code == 204
    assert App(tenant_a).sign_in("hala").status_code == 401

    with tenant_context(tenant_a.id):
        branch = Branch.objects.get(code=1)
    half = owner.put(f"/api/web/org/branches/{branch.pk}/",
                     {"code": 1, "name": branch.name, "latitude": "30.044400"},
                     content_type="application/json")
    assert half.status_code == 400 and "longitude" in half.json()["error"]["fields"]
    whole = owner.put(f"/api/web/org/branches/{branch.pk}/",
                      {"code": 1, "name": branch.name, "latitude": "30.044400",
                       "longitude": "31.235700", "radius_m": 150},
                      content_type="application/json")
    assert whole.status_code == 200
    assert owner.get("/reports/tracking_sessions/").status_code == 200


def test_every_app_endpoint_needs_the_app():
    """/api/v1/ answers only members who may use the app, but for signing in."""
    from django.urls import get_resolver

    from apps.mobile.views import CanUseApp

    public = {"api_login", "api_refresh", "api_verify"}
    loose = []
    for pattern in get_resolver().url_patterns:
        if str(pattern.pattern) != "api/v1/":
            continue
        for route in pattern.url_patterns:
            cls = route.callback.cls
            if route.name not in public and not any(issubclass(p, CanUseApp)
                                                    for p in cls.permission_classes):
                loose.append(route.name)
    assert loose == []
