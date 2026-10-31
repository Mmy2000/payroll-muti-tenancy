"""Each client's WhatsApp this month, read inside that client's own context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Count, Q
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.messaging.models import LinkStatus, Message, MessageStatus, WhatsAppLink
from apps.platform.tenants import features
from apps.platform.tenants.models import Tenant, TenantStatus


@dataclass
class ClientRow:
    tenant: Tenant
    feature_on: bool
    link_status: str
    link_label: str
    phone: str
    sent: int
    failed: int
    waiting: int
    last_sent: datetime | None


def _client(tenant: Tenant, month_start: datetime) -> ClientRow:
    with tenant_context(tenant.id):
        link = WhatsAppLink.objects.first()
        status = link.status if link else LinkStatus.NOT_LINKED
        month = Message.objects.filter(created_at__gte=month_start)
        counts = month.aggregate(
            sent=Count("pk", filter=Q(status=MessageStatus.SENT)),
            failed=Count("pk", filter=Q(status=MessageStatus.FAILED)),
            waiting=Count("pk", filter=Q(status=MessageStatus.QUEUED)))
        last = (Message.objects.filter(status=MessageStatus.SENT).order_by("-sent_at")
                .values_list("sent_at", flat=True).first())
    return ClientRow(tenant=tenant, feature_on=features.is_enabled(tenant.id, "whatsapp"),
                     link_status=status, link_label=str(LinkStatus(status).label),
                     phone=link.phone if link else "", last_sent=last, **counts)


def client_rows() -> list[ClientRow]:
    """Clients with WhatsApp on, or with messages this month, those using it first."""
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tenants = Tenant.objects.filter(status__in=(TenantStatus.ACTIVE, TenantStatus.SUSPENDED))
    rows = [_client(tenant, month_start) for tenant in tenants.order_by("name")]
    rows = [row for row in rows if row.feature_on or row.sent or row.failed or row.waiting]
    return sorted(rows, key=lambda row: (-row.sent, row.tenant.name))
