"""Linking the client's WhatsApp number, and sending payslips from it.

Payslips of an approved or paid run go out one message per employee, as jobs spaced
`gap_seconds` apart (PayRole's browser waited 10 s between two, and stopped when its tab
closed). Each message carries the payslip as a PDF, made when it is sent. A payslip already
sent is not sent again unless asked; employees without a usable number are listed, not sent.

Permissions: `messaging.whatsapp.link` (the number and the wording), `messaging.send`
(sending payslips), `messaging.view` (the sent messages).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import Conflict, DomainError, NotFound, ValidationError
from apps.core.tenancy.context import require_current_tenant_id
from apps.platform.jobs.registry import enqueue

from . import gateways
from .models import LinkStatus, Message, MessageKind, MessageStatus, WhatsAppLink
from .permissions import LINK, SEND


def link_for() -> WhatsAppLink:
    link = WhatsAppLink.objects.select_for_update().first()
    return link or WhatsAppLink.objects.create()


# --- the number --------------------------------------------------------------------------------


def start_link(*, actor=None) -> dict:
    """Start linking: the next look at the link shows the QR to scan."""
    if actor is not None:
        actor.require(LINK)
    from apps.platform.tenants.models import Tenant

    with transaction.atomic():
        link = link_for()
        if not link.session_id:
            slug = Tenant.objects.get(pk=require_current_tenant_id()).slug
            link.session_id = gateways.new_session_id(slug)
        result = gateways.start(link.session_id)
        if not result.ok:
            raise DomainError(result.error, code="MESSAGING_GATEWAY")
        link.status, link.error = LinkStatus.WAITING, ""
        link.save(update_fields=["session_id", "status", "error", "updated_at"])
    return look(actor=None)


def look(*, actor=None) -> dict:
    """The link as the gateway sees it now: {status, phone, qr}."""
    if actor is not None:
        actor.require(LINK)
    with transaction.atomic():
        link = link_for()
        if not link.session_id:
            return {"status": link.status, "phone": "", "qr": ""}
        result = gateways.state(link.session_id)
        link.checked_at = timezone.now()
        if not result.ok:
            link.error = result.error
            link.save(update_fields=["checked_at", "error", "updated_at"])
            return {"status": link.status, "phone": link.phone, "qr": "", "error": result.error}
        found = result.data["status"]
        status = {"connected": LinkStatus.LINKED, "qr": LinkStatus.WAITING,
                  "starting": LinkStatus.WAITING, "disconnected": LinkStatus.BROKEN
                  }.get(found, LinkStatus.NOT_LINKED)
        if status == LinkStatus.LINKED and link.status != LinkStatus.LINKED:
            link.linked_at = timezone.now()
        link.status, link.phone, link.error = status, result.data.get("phone", ""), ""
        link.save(update_fields=["status", "phone", "linked_at", "checked_at", "error",
                                 "updated_at"])
    return {"status": status, "phone": link.phone, "qr": result.data.get("qr", "")}


def unlink(*, actor=None) -> None:
    if actor is not None:
        actor.require(LINK)
    with transaction.atomic():
        link = link_for()
        if link.session_id:
            gateways.logout(link.session_id)
        link.session_id, link.status, link.phone = "", LinkStatus.NOT_LINKED, ""
        link.save(update_fields=["session_id", "status", "phone", "updated_at"])


@dataclass(frozen=True)
class WordingInput:
    payslip_message: str
    gap_seconds: int = 10


PLACEHOLDERS = ("{name}", "{eco}", "{date1}", "{date2}", "{net}", "{company}")


def save_wording(data: WordingInput, *, actor=None) -> WhatsAppLink:
    if actor is not None:
        actor.require(LINK)
    errors = {}
    if not data.payslip_message.strip():
        errors["payslip_message"] = [_("Write the message sent with a payslip.")]
    if not 5 <= data.gap_seconds <= 600:
        errors["gap_seconds"] = [_("Between 5 and 600 seconds.")]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
    with transaction.atomic():
        link = link_for()
        link.payslip_message, link.gap_seconds = data.payslip_message.strip(), data.gap_seconds
        link.save(update_fields=["payslip_message", "gap_seconds", "updated_at"])
    return link


# --- sending ---------------------------------------------------------------------------------


def payslip_text(template: str, slip) -> str:
    """PayRole's placeholders, replaced as plain text (not str.format: a brace in the wording
    is just a brace)."""
    from apps.org.models import TenantProfile

    profile = TenantProfile.objects.first()
    values = {"{name}": slip.employee.name, "{eco}": str(slip.employee.code),
              "{date1}": slip.run.period.start.isoformat(),
              "{date2}": slip.run.period.end.isoformat(), "{net}": f"{slip.net:,.2f}",
              "{company}": profile.display_name if profile else ""}
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def _require_linked(link: WhatsAppLink) -> None:
    if link.status != LinkStatus.LINKED or not link.session_id:
        raise DomainError(_("Link the company's WhatsApp number first (Settings → WhatsApp)."),
                          code="MESSAGING_NOT_LINKED")


@dataclass
class SendOutcome:
    queued: int = 0
    no_phone: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)


def send_payslips(run_id: int, *, slip_ids: list[int] | None = None, again: bool = False,
                  actor=None) -> SendOutcome:
    from apps.payroll.models import PayrollRun, RunStatus
    from apps.payroll.selectors import visible_runs

    if actor is not None:
        actor.require(SEND)
    with transaction.atomic():
        link = link_for()
        _require_linked(link)
        runs = visible_runs(actor) if actor is not None else PayrollRun.objects.all()
        run = runs.filter(pk=run_id).first()
        if run is None:
            raise NotFound(_("Not found."))
        if run.status not in (RunStatus.APPROVED, RunStatus.PAID):
            raise Conflict(_("Only the payslips of an approved run are sent."),
                           code="MESSAGING_RUN_STATE")
        slips = run.payslips.select_related("employee", "run__period")
        if slip_ids:
            slips = slips.filter(pk__in=slip_ids)
        sent = set(Message.objects.filter(payslip__run=run, status__in=(
            MessageStatus.QUEUED, MessageStatus.SENT)).values_list("payslip_id", flat=True))
        outcome, when = SendOutcome(), timezone.now()
        for slip in slips.order_by("employee__code"):
            if slip.pk in sent and not again:
                outcome.already.append(slip.employee.name)
                continue
            phone = gateways.phone_digits(slip.employee.phone)
            if not phone:
                outcome.no_phone.append(slip.employee.name)
                continue
            message = Message.objects.create(
                kind=MessageKind.PAYSLIP, phone=phone, employee=slip.employee, payslip=slip,
                text=payslip_text(link.payslip_message, slip),
                sent_by=getattr(actor, "user", None))
            enqueue("messaging.send", message_id=message.pk, run_at=when)
            when += timedelta(seconds=link.gap_seconds)
            outcome.queued += 1
    return outcome


def send_test(phone: str, *, actor=None) -> Message:
    if actor is not None:
        actor.require(LINK)
    digits = gateways.phone_digits(phone)
    if not digits:
        raise ValidationError(_("Please correct the highlighted fields."),
                              fields={"phone": [_("Enter a mobile number.")]})
    with transaction.atomic():
        _require_linked(link_for())
        message = Message.objects.create(
            kind=MessageKind.TEST, phone=digits, sent_by=getattr(actor, "user", None),
            text=_("A test message from the payroll system: WhatsApp is linked."))
        enqueue("messaging.send", message_id=message.pk)
    return message


def send_again(message_id: int, *, actor=None) -> Message:
    if actor is not None:
        actor.require(SEND)
    with transaction.atomic():
        message = Message.objects.select_for_update().filter(pk=message_id).first()
        if message is None:
            raise NotFound(_("Not found."))
        if message.status != MessageStatus.FAILED:
            raise Conflict(_("Only a failed message is sent again."), code="MESSAGING_STATE")
        message.status, message.error = MessageStatus.QUEUED, ""
        message.save(update_fields=["status", "error", "updated_at"])
        enqueue("messaging.send", message_id=message.pk)
    return message
