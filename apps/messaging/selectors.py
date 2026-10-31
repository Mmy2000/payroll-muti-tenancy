"""What the WhatsApp pages read."""

from __future__ import annotations

from django.db.models import QuerySet

from .models import Message, WhatsAppLink


def whatsapp_link() -> WhatsAppLink:
    """The client's link; an unsaved blank one until a number was linked."""
    return WhatsAppLink.objects.first() or WhatsAppLink()


def sent_messages() -> QuerySet[Message]:
    return Message.objects.select_related("employee", "payslip__run").order_by("-id")


def by_status(queryset: QuerySet[Message], value: str) -> QuerySet[Message]:
    return queryset if value == "all" else queryset.filter(status=value)
