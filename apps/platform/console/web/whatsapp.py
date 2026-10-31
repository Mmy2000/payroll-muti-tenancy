"""Console → WhatsApp: the gateway, in one place. On or off, its address and key, whether it
answers, and each client's number and messages this month. Everything else follows these
settings: apps.messaging.gateways reads them on every call, and `run_wa_gateway` keeps the
gateway running to match, so a change needs no file edit and no restart."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.messaging import gateways
from apps.platform.tenants.models import WhatsAppService
from apps.platform.tenants.services import replace_whatsapp_key, save_whatsapp_settings

from ..selectors.whatsapp import client_rows
from .common import staff_required
from .forms import WhatsAppServiceForm

GATEWAY_DIR = settings.BASE_DIR / "ops" / "wa-gateway"


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
        save_whatsapp_settings(form.instance, secret=form.cleaned_data["secret"],
                               changes=_changed(form), actor=request.user)
        messages.success(request, _("Saved."))
        return redirect("console-whatsapp")
    return render(request, "console/whatsapp.html", {
        "section": "whatsapp", "service": service, "form": form, "state": _state(service),
        "installed": (GATEWAY_DIR / "node_modules").is_dir(),
        "in_memory": gateways.console(), "rows": client_rows(),
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
    replace_whatsapp_key(service, actor=request.user)
    messages.success(request, _("New key in use. The gateway restarts by itself; linked numbers "
                                "stay linked."))
    return redirect("console-whatsapp")
