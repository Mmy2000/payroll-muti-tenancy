"""Console → WhatsApp: the gateway, in one place. On or off, its address and key, whether it
answers, and each client's number and messages this month. Everything else follows these
settings: apps.messaging.gateways reads them on every call, and `run_wa_gateway` keeps the
gateway running to match, so a change needs no file edit and no restart."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.tenancy import tenant_context
from apps.messaging import gateways
from apps.messaging.models import LinkStatus, Message, MessageStatus, WhatsAppLink
from apps.platform.tenants import features
from apps.platform.tenants.models import Tenant, TenantStatus, WhatsAppService

from .forms import WhatsAppServiceForm
from .views import record, staff_required

GATEWAY_DIR = settings.BASE_DIR / "ops" / "wa-gateway"


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


def _clients() -> list[ClientRow]:
    """Clients with WhatsApp on, or with messages this month, those using it first."""
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tenants = Tenant.objects.filter(status__in=(TenantStatus.ACTIVE, TenantStatus.SUSPENDED))
    rows = [_client(tenant, month_start) for tenant in tenants.order_by("name")]
    rows = [row for row in rows if row.feature_on or row.sent or row.failed or row.waiting]
    return sorted(rows, key=lambda row: (-row.sent, row.tenant.name))


def _state(service: WhatsAppService) -> dict:
    """What the status card says: off, running, or why not."""
    if not service.ready:
        return {"code": "off", "sessions": 0, "problem": ""}
    health = gateways.health()
    if health.ok:
        return {"code": "running", "sessions": health.data.get("sessions", 0), "problem": ""}
    return {"code": "down", "sessions": 0, "problem": health.error}


def _changed(form) -> dict:
    """What to log: the fields that changed, never the key's value."""
    changed = {name: form.cleaned_data[name] for name in form.changed_data if name != "secret"}
    return {**changed, **({"key": "replaced"} if form.cleaned_data["secret"] else {})}


@staff_required
def whatsapp(request):
    service = WhatsAppService.load()
    form = WhatsAppServiceForm(request.POST or None, instance=service)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if form.cleaned_data["secret"]:
            saved.secret = form.cleaned_data["secret"]
        elif saved.enabled and not saved.key:
            saved.new_secret()
        saved.save()
        record(request, "whatsapp.settings", None, **_changed(form))
        messages.success(request, _("Saved."))
        return redirect("console-whatsapp")
    return render(request, "console/whatsapp.html", {
        "section": "whatsapp", "service": service, "form": form, "state": _state(service),
        "installed": (GATEWAY_DIR / "node_modules").is_dir(),
        "in_memory": gateways.console(), "rows": _clients(),
        "month": timezone.localdate()})


@staff_required
@require_POST
def new_key(request):
    """Replace the key. On this server the gateway follows in a few seconds; one elsewhere has
    to be given its new key, so there a key is pasted instead."""
    service = WhatsAppService.load()
    if not service.is_local:
        messages.error(request, _("This gateway is on another server: paste its key instead."))
        return redirect("console-whatsapp")
    service.new_secret()
    service.save()
    record(request, "whatsapp.key")
    messages.success(request, _("New key in use. The gateway restarts by itself; linked numbers "
                                "stay linked."))
    return redirect("console-whatsapp")
