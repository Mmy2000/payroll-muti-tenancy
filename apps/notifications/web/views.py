"""The notifications page: everything the member was told, newest first, and what waits; and
the live stream behind the bell."""

from django.core.handlers.asgi import ASGIRequest
from django.core.paginator import Paginator
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render

from apps.iam.authz import permission_required

from .. import selectors
from .. import selectors as attention
from ..present import item
from ..stream import events


@permission_required("authenticated")
def notifications(request):
    member = request.actor.membership
    rows = selectors.newest_for(member, unread_only=request.GET.get("unread") == "1")
    page = Paginator(rows, 30).get_page(request.GET.get("page"))
    return render(request, "notifications/notifications.html", {
        "page": page, "items": [item(r) for r in page.object_list],
        "attention": attention.waiting(request.actor),
        "unread": selectors.unread_count(member), "only_unread": request.GET.get("unread") == "1"})


def stream(request):
    """The bell's live connection (static/core/js/live.js). It needs an async server: anywhere
    else it answers 503 at once and the bell polls, rather than tying up a worker."""
    actor = getattr(request, "actor", None)
    if actor is None:
        return HttpResponse(status=401)
    if not isinstance(request, ASGIRequest):
        return HttpResponse(status=503)
    last = request.headers.get("Last-Event-ID", "")
    response = StreamingHttpResponse(
        events(request.tenant.pk, actor.membership.pk, int(last) if last.isdigit() else None),
        content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"  # nginx must pass it on as it comes
    return response
