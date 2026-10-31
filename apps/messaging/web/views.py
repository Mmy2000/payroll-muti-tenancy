"""WhatsApp pages: linking the number and its wording (Settings → WhatsApp), and the messages
sent (Settings → Sent messages)."""

from __future__ import annotations

from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.listing import Choice, ListQuery
from apps.iam.authz import permission_required

from .. import gateways, services
from ..models import Message, MessageStatus, WhatsAppLink

STATUS_TABS = [("all", _lazy("All")), (MessageStatus.QUEUED, _lazy("Waiting")),
               (MessageStatus.SENT, _lazy("Sent")), (MessageStatus.FAILED, _lazy("Failed"))]


def _by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


@permission_required(services.LINK)
def whatsapp(request):
    link = WhatsAppLink.objects.first() or WhatsAppLink()
    return render(request, "messaging/whatsapp.html", {
        "link": link, "placeholders": services.PLACEHOLDERS, "ready": gateways.ready()})


@permission_required(services.VIEW)
def messages(request):
    found = ListQuery(request, permission=services.VIEW, search=("phone", "employee__name"),
                      date_field="created_at__date", branch_field="",
                      choices=[Choice("status", _("Status"), STATUS_TABS, apply=_by_status,
                                      value="all", tabs=True)])
    rows = found.apply(Message.objects.select_related("employee", "payslip__run"))
    return render(request, "messaging/messages.html", {
        "filters": found, "page": found.page(rows.order_by("-id")),
        "can_send": request.actor.can(services.SEND)})
