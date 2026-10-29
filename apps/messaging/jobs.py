"""Sending one WhatsApp message (a payslip with its PDF, or a test), retried when the gateway
fails; the last failure is written on the message. Nothing is sent while the client's WhatsApp
feature is off."""

import re

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.platform.jobs.registry import JobFailed, task


def _note_error(payload, error, final):
    from .models import Message, MessageStatus

    message = Message.objects.filter(pk=payload.get("message_id")).first()
    if message is not None and message.status == MessageStatus.QUEUED:
        # The worker writes "RuntimeError: <reason>": people read the reason.
        message.error = re.sub(r"^\w+: ", "", str(error))[:300]
        if final:
            message.status = MessageStatus.FAILED
        message.save(update_fields=["error", "status", "updated_at"])


@task("messaging.send", label=_lazy("Send a WhatsApp message"), max_attempts=3,
      on_error=_note_error)
def send(message_id):
    from apps.core.tenancy.context import require_current_tenant_id
    from apps.platform.tenants import features

    from . import gateways
    from .models import Message, MessageKind, MessageStatus, WhatsAppLink

    message = Message.objects.select_for_update().filter(pk=message_id).first()
    if message is None or message.status != MessageStatus.QUEUED:
        return  # sent already, or gone
    if not features.is_enabled(require_current_tenant_id(), "whatsapp"):
        raise JobFailed(_("WhatsApp is switched off for this company."))
    link = WhatsAppLink.objects.first()
    if link is None or not link.session_id:
        raise JobFailed(_("The company's WhatsApp number is not linked."))
    pdf, filename = None, ""
    if message.kind == MessageKind.PAYSLIP:
        if message.payslip is None:
            raise JobFailed(_("The payslip no longer exists."))
        from apps.payroll import printing

        slip = message.payslip
        pdf = printing.payslips_pdf(slip.run, [slip])
        filename = printing.filename(slip.run, slip)
    result = gateways.send(link.session_id, phone=message.phone, text=message.text, pdf=pdf,
                           filename=filename)
    if not result.ok:
        raise RuntimeError(result.error)  # retried; the last failure is written on it
    message.status, message.sent_at, message.error = MessageStatus.SENT, timezone.now(), ""
    message.save(update_fields=["status", "sent_at", "error", "updated_at"])
