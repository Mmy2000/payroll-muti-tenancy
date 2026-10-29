"""WhatsApp from the client's own number (PayRole `whatsapp_gateway`): its link to the gateway,
and every message sent (the outbox and the log in one: queued → sent or failed).

PayRole's browser sent payslips one by one while its tab stayed open; here each message is a job
(apps/messaging/jobs.py), spaced out, retried, and shown with its result.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel

# PayRole's default (whatsapp_gateway/models.py), with its placeholders.
DEFAULT_PAYSLIP_MESSAGE = ("مرحبا {name}\nمرفق شيت مرتبك عن الفترة من {date1} الى {date2}\n"
                           "صافى المرتب: {net} جنيه\n{company}")


class LinkStatus(models.TextChoices):
    NOT_LINKED = "not_linked", _("Not linked")
    WAITING = "waiting", _("Waiting for the QR scan")
    LINKED = "linked", _("Linked")
    BROKEN = "broken", _("Disconnected")


class WhatsAppLink(TenantScopedModel):
    session_id = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=12, choices=LinkStatus.choices,
                              default=LinkStatus.NOT_LINKED)
    phone = models.CharField(max_length=20, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    payslip_message = models.TextField(default=DEFAULT_PAYSLIP_MESSAGE)
    gap_seconds = models.PositiveSmallIntegerField(default=10)  # between two payslips

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"],
                                               name="messaging_link_one_uniq")]


class MessageKind(models.TextChoices):
    PAYSLIP = "payslip", _("Payslip")
    TEST = "test", _("Test")


class MessageStatus(models.TextChoices):
    QUEUED = "queued", _("Waiting to be sent")
    SENT = "sent", _("Sent")
    FAILED = "failed", _("Failed")


class Message(TenantScopedModel):
    kind = models.CharField(max_length=10, choices=MessageKind.choices)
    status = models.CharField(max_length=8, choices=MessageStatus.choices,
                              default=MessageStatus.QUEUED)
    phone = models.CharField(max_length=20)  # as sent: digits, with the country code
    text = models.TextField()
    employee = models.ForeignKey("employees.Employee", null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="+")
    payslip = models.ForeignKey("payroll.Payslip", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "payslip", "status"],
                                name="messaging_message_slip_idx")]
