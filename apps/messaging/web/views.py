"""WhatsApp pages: linking the number and its wording (Settings → WhatsApp), and the messages
sent (Settings → Sent messages)."""

from __future__ import annotations

from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.iam.authz import permission_required
from apps.org.listing import Choice, ListQuery, by_status

from .. import gateways, permissions, selectors, services
from ..models import MessageStatus

STATUS_TABS = [("all", _lazy("All")), (MessageStatus.QUEUED, _lazy("Waiting")),
               (MessageStatus.SENT, _lazy("Sent")), (MessageStatus.FAILED, _lazy("Failed"))]


@permission_required(permissions.LINK)
def whatsapp(request):
    return render(request, "messaging/whatsapp.html", {
        "link": selectors.whatsapp_link(), "placeholders": services.PLACEHOLDERS,
        "ready": gateways.ready()})


@permission_required(permissions.VIEW)
def messages(request):
    found = ListQuery(request, permission=permissions.VIEW, search=("phone", "employee__name"),
                      date_field="created_at__date", branch_field="",
                      choices=[Choice("status", _("Status"), STATUS_TABS,
                                      apply=by_status, value="all", tabs=True)])
    rows = found.apply(selectors.sent_messages())
    return render(request, "messaging/messages.html", {
        "filters": found, "page": found.page(rows),
        "can_send": request.actor.can(permissions.SEND)})
