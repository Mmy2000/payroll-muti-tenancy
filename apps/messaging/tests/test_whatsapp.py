"""WhatsApp payslips: PayRole's phone rules and wording, linking the number, one job per
payslip spaced out, retries, and nothing sent twice or while switched off."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.core.errors import Conflict, DomainError
from apps.core.tenancy import tenant_context
from apps.messaging import gateways, services
from apps.messaging.models import LinkStatus, Message, MessageStatus
from apps.payroll.services import lifecycle as payroll_lifecycle
from apps.payroll.services import runs as payroll
from apps.platform.jobs.models import Job
from apps.platform.jobs.worker import run_pending
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from conftest import login


def test_phone_numbers_as_payrole_read_them():
    assert gateways.phone_digits("01001234567") == "201001234567"
    assert gateways.phone_digits("+20 100 123 4567") == "201001234567"
    assert gateways.phone_digits("00966501234567") == "966501234567"
    assert gateways.phone_digits("1001234567") == "201001234567"
    assert gateways.phone_digits("0000000000") == ""  # one digit over and over
    assert gateways.phone_digits("12345") == ""


def _switch(tenant, **keys):
    for key, enabled in keys.items():
        TenantFeature.objects.update_or_create(tenant=tenant, key=key,
                                               defaults={"enabled": enabled})
    features.forget(tenant.pk)


@pytest.fixture
def paid_run(tenant_a, make_employee):
    _switch(tenant_a, attendance=False, whatsapp=True)
    make_employee(tenant_a, 1, name="Mona Adel", phone="01001234567", salary=D(6000))
    make_employee(tenant_a, 2, name="Karim Fathy", salary=D(3000))  # no phone
    with tenant_context(tenant_a.id):
        run = payroll.create_run(payroll.RunInput(frequency="monthly", day=date(2026, 10, 15)))
        payroll_lifecycle.approve_run(run.pk)
        services.start_link()
        services.look()  # the console "scans" the QR
        services.look()
    return run


@pytest.mark.django_db
def test_payslips_go_one_job_each_and_never_twice(tenant_a, paid_run, monkeypatch):
    from apps.payroll import printing

    monkeypatch.setattr(printing, "payslips_pdf", lambda run, slips: b"%PDF-1.7 test")
    gateways.OUTBOX.clear()
    with tenant_context(tenant_a.id):
        outcome = services.send_payslips(paid_run.pk)
        assert (outcome.queued, outcome.no_phone) == (1, ["Karim Fathy"])
        assert Job.objects.filter(name="messaging.send").count() == 1
        again = services.send_payslips(paid_run.pk)  # a second click
        assert (again.queued, again.already) == (0, ["Mona Adel"])
    run_pending()
    assert len(gateways.OUTBOX) == 1
    sent = gateways.OUTBOX[0]
    assert sent["phone"] == "201001234567" and sent["filename"].endswith(".pdf")
    assert "مرحبا Mona Adel" in sent["text"] and "6,000.00" in sent["text"]
    with tenant_context(tenant_a.id):
        assert Message.objects.get().status == MessageStatus.SENT


@pytest.mark.django_db
def test_a_gateway_failure_is_retried_then_written_down(tenant_a, paid_run, monkeypatch):
    from apps.payroll import printing

    monkeypatch.setattr(printing, "payslips_pdf", lambda run, slips: b"%PDF-1.7 test")
    monkeypatch.setattr(gateways, "send", lambda *a, **k: gateways.Result(
        False, "This number is not on WhatsApp."))
    with tenant_context(tenant_a.id):
        services.send_payslips(paid_run.pk)
        job = Job.objects.get(name="messaging.send")
    for _attempt in range(3):
        Job.objects.filter(pk=job.pk).update(run_at=job.run_at)  # due again at once
        run_pending()
    with tenant_context(tenant_a.id):
        message = Message.objects.get()
        assert message.status == MessageStatus.FAILED
        assert message.error == "This number is not on WhatsApp."
        services.send_again(message.pk)
        message.refresh_from_db()
        assert message.status == MessageStatus.QUEUED


@pytest.mark.django_db
def test_nothing_is_sent_unlinked_unapproved_or_switched_off(tenant_a, make_employee):
    _switch(tenant_a, attendance=False, whatsapp=True)
    make_employee(tenant_a, 1, phone="01001234567")
    with tenant_context(tenant_a.id):
        run = payroll.create_run(payroll.RunInput(frequency="monthly", day=date(2026, 10, 15)))
        with pytest.raises(DomainError):  # no number linked
            services.send_payslips(run.pk)
        services.start_link()
        services.look()
        assert services.look()["status"] == LinkStatus.LINKED
        with pytest.raises(Conflict):  # a draft run
            services.send_payslips(run.pk)
        payroll_lifecycle.approve_run(run.pk)
        services.send_payslips(run.pk)
    _switch(tenant_a, whatsapp=False)
    gateways.OUTBOX.clear()
    run_pending()
    assert gateways.OUTBOX == []
    with tenant_context(tenant_a.id):
        assert Message.objects.get().status == MessageStatus.FAILED  # switched off: not retried


@pytest.mark.django_db
def test_the_pages(tenant_a, paid_run):
    client = login(tenant_a, language="en")
    page = client.get("/settings/whatsapp/").content.decode()
    assert "Linked" in page and "{name}" in page
    assert client.get("/settings/messages/").status_code == 200
    run_page = client.get(f"/payroll/{paid_run.pk}/").content.decode()
    assert "Send payslips on WhatsApp" in run_page
    queued = client.post("/api/web/messaging/whatsapp/payslips/", {"run_id": paid_run.pk},
                         content_type="application/json")
    assert queued.status_code == 201 and queued.json()["no_phone"] == ["Karim Fathy"]
    wording = client.put("/api/web/messaging/whatsapp/wording/",
                         {"payslip_message": "Hi {name}", "gap_seconds": 2},
                         content_type="application/json")
    assert "gap_seconds" in wording.json()["error"]["fields"]
