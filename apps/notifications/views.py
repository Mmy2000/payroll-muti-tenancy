"""The notifications page: everything the member was told, newest first, and what waits."""

from django.core.paginator import Paginator
from django.shortcuts import render

from apps.iam.authz import permission_required

from . import attention, services
from .api import item


@permission_required("authenticated")
def notifications(request):
    member = request.actor.membership
    rows = services.for_member(member)
    if request.GET.get("unread") == "1":
        rows = rows.filter(read_at__isnull=True)
    page = Paginator(rows.order_by("-id"), 30).get_page(request.GET.get("page"))
    return render(request, "notifications/notifications.html", {
        "page": page, "items": [item(r) for r in page.object_list],
        "attention": attention.waiting(request.actor),
        "unread": services.unread_count(member), "only_unread": request.GET.get("unread") == "1"})
