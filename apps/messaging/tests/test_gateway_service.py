"""The WhatsApp gateway run from the platform console (tenants.WhatsAppService): nothing in
`.env`, the key encrypted and never shown, and `run_wa_gateway` following the settings."""

import json

import pytest
from django.test import Client

from apps.core.tenancy import tenant_context
from apps.messaging import gateways
from apps.messaging.management.commands import run_wa_gateway as supervisor
from apps.messaging.models import LinkStatus, Message, MessageKind, MessageStatus, WhatsAppLink
from apps.platform.tenants.models import PlatformEvent, TenantFeature, WhatsAppService
from conftest import PASSWORD

pytestmark = pytest.mark.django_db
HOST = "admin.localhost"


@pytest.fixture
def staff(db):
    from apps.iam.models import User

    User.objects.create_superuser(email="ops@platform.test", password=PASSWORD,
                                  display_name="Ops")
    client = Client(HTTP_HOST=HOST)
    client.cookies["django_language"] = "en"
    assert client.post("/login/", {"username": "ops@platform.test",
                                   "password": PASSWORD}).status_code == 302
    return client


def _save(staff, **data):
    return staff.post("/whatsapp/", {"url": "http://127.0.0.1:3002", **data})


def test_switching_it_on_makes_an_encrypted_key_nobody_sees(staff):
    assert _save(staff, enabled="on").status_code == 302
    service = WhatsAppService.load()
    assert service.ready and len(service.secret) > 30
    assert service.secret not in service.key  # encrypted in the database

    page = staff.get("/whatsapp/").content.decode()
    assert service.secret not in page and service.key not in page
    event = PlatformEvent.objects.get(action="whatsapp.settings")
    assert event.detail == {"enabled": "True"} and service.secret not in json.dumps(event.detail)


def test_another_servers_key_is_pasted_and_never_logged(staff):
    _save(staff, enabled="on", url="https://wa.example.com", secret="their-long-key")
    service = WhatsAppService.load()
    assert service.secret == "their-long-key" and not service.is_local
    event = PlatformEvent.objects.get(action="whatsapp.settings")
    assert event.detail["key"] == "replaced" and "their-long-key" not in json.dumps(event.detail)

    # Its key lives on the other server: replacing it here would only break the link.
    staff.post("/whatsapp/key/")
    assert WhatsAppService.load().secret == "their-long-key"


def test_replacing_the_key(staff):
    _save(staff, enabled="on")
    before = WhatsAppService.load().secret
    assert staff.post("/whatsapp/key/").status_code == 302
    assert WhatsAppService.load().secret != before
    assert PlatformEvent.objects.filter(action="whatsapp.key").exists()


def test_only_platform_staff(tenant_a):
    assert Client(HTTP_HOST=HOST).get("/whatsapp/").status_code == 302
    assert Client(HTTP_HOST="alpha.localhost").get("/whatsapp/").status_code == 404
    assert Client(HTTP_HOST=HOST).post("/whatsapp/key/").status_code == 302


def test_the_client_uses_the_consoles_settings(staff, monkeypatch):
    assert gateways.console() and gateways.ready()  # development: kept in memory

    _save(staff, enabled="on", url="http://127.0.0.1:3999")
    assert not gateways.console() and gateways.ready()
    called = {}

    class Reply:
        status = 200

        def read(self):
            return b'{"ok": true, "sessions": 2}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        called.update(url=request.full_url, key=request.get_header("X-api-key"))
        return Reply()

    monkeypatch.setattr(gateways, "urlopen", urlopen)
    assert gateways.health().data["sessions"] == 2
    assert called == {"url": "http://127.0.0.1:3999/health",
                      "key": WhatsAppService.load().secret}


def test_switched_off_nothing_can_be_sent(staff, settings):
    settings.WHATSAPP_CONSOLE = False
    _save(staff)
    assert not gateways.ready()
    assert gateways.send("s", phone="201000000000", text="hi").ok is False


def test_the_status_says_what_is_wrong(staff, monkeypatch):
    assert "Off" in staff.get("/whatsapp/").content.decode()
    _save(staff, enabled="on")
    monkeypatch.setattr(gateways, "health", lambda: gateways.Result(True, data={"sessions": 3}))
    assert "3 numbers connected" in staff.get("/whatsapp/").content.decode()
    monkeypatch.setattr(gateways, "health", lambda: gateways.Result(False, "It is down."))
    page = staff.get("/whatsapp/").content.decode()
    assert "Not answering" in page and "It is down." in page


def test_each_clients_number_and_messages(staff, tenant_a, tenant_b):
    TenantFeature.objects.create(tenant=tenant_a, key="whatsapp", enabled=True)
    with tenant_context(tenant_a.id):
        WhatsAppLink.objects.create(status=LinkStatus.LINKED, phone="201011112222")
        Message.objects.create(kind=MessageKind.TEST, phone="2010", text="a",
                               status=MessageStatus.SENT)
        Message.objects.create(kind=MessageKind.TEST, phone="2010", text="b",
                               status=MessageStatus.FAILED)
    page = staff.get("/whatsapp/").content.decode()
    assert "Alpha" in page and "201011112222" in page
    assert "Bravo" not in page  # WhatsApp off, no messages


class FakeProcess:
    def __init__(self, command, *, cwd, env):
        self.env, self.code, self.stopped = env, None, False
        FakeProcess.started.append(self)

    def poll(self):
        return self.code

    @property
    def returncode(self):
        return self.code

    def terminate(self):
        self.stopped = True

    def wait(self, timeout):
        return 0


@pytest.fixture
def command(monkeypatch, tmp_path):
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(supervisor, "GATEWAY", tmp_path)
    monkeypatch.setattr(supervisor.shutil, "which", lambda name: "node")
    monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(supervisor, "close_old_connections", lambda: None)
    FakeProcess.started = []
    run = supervisor.Command()
    run.child, run.running, run.said, run.retry_at = None, None, "", 0.0
    return run


def _turn(*, enabled=True, url="http://127.0.0.1:3555"):
    service = WhatsAppService.load()
    service.enabled, service.url = enabled, url
    if not service.key:
        service.new_secret()
    service.save()
    return service


def test_the_supervisor_follows_the_console(command):
    command.step()
    assert FakeProcess.started == []  # off: nothing runs

    service = _turn()
    command.step()
    first = FakeProcess.started[0]
    assert first.env["WA_GATEWAY_KEY"] == service.secret
    assert (first.env["HOST"], first.env["PORT"]) == ("127.0.0.1", "3555")

    command.step()
    assert len(FakeProcess.started) == 1  # nothing changed

    service.new_secret()
    service.save()
    command.step()
    assert first.stopped and len(FakeProcess.started) == 2
    assert FakeProcess.started[1].env["WA_GATEWAY_KEY"] == service.secret

    _turn(enabled=False)
    command.step()
    assert FakeProcess.started[1].stopped and command.child is None


def test_the_supervisor_brings_a_crashed_gateway_back(command, monkeypatch):
    _turn()
    clock = [100.0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock[0])
    command.step()
    FakeProcess.started[0].code = 1

    command.step()  # waits, so a failing gateway doesn't spin
    assert len(FakeProcess.started) == 1
    clock[0] += supervisor.RESTART_AFTER + 1
    command.step()
    assert len(FakeProcess.started) == 2


def test_the_supervisor_leaves_another_servers_gateway_alone(command):
    _turn(url="https://wa.example.com")
    command.step()
    assert FakeProcess.started == []


def test_the_supervisor_says_when_the_gateway_is_not_installed(command, monkeypatch):
    monkeypatch.setattr(supervisor.shutil, "which", lambda name: None)
    _turn()
    command.step()
    assert FakeProcess.started == []
    assert "npm ci" in command.said
