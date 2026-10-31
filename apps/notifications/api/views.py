"""The browser's API for notifications (the bell, static/core/js/bell.js): GET the latest and
what needs attention (?count=1: the unread count only), POST <id>/read/, POST read-all/."""

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.iam.catalog import AUTHENTICATED

from .. import selectors, services
from .. import selectors as attention
from ..present import item

LATEST = 20


class NotificationsView(APIView):
    required_permissions = {"GET": AUTHENTICATED}

    def get(self, request):
        member = request.actor.membership
        unread = selectors.unread_count(member)
        if request.GET.get("count") == "1":
            return Response({"unread": unread})
        rows = selectors.newest_for(member)[:LATEST]
        return Response({"unread": unread, "results": [item(r) for r in rows],
                         "attention": attention.waiting(request.actor)})


class ReadView(APIView):
    required_permissions = {"POST": AUTHENTICATED}

    def post(self, request, pk):
        services.mark_read(request.actor.membership, [pk])
        return Response({"unread": selectors.unread_count(request.actor.membership)})


class ReadAllView(APIView):
    required_permissions = {"POST": AUTHENTICATED}

    def post(self, request):
        marked = services.mark_read(request.actor.membership)
        return Response({"marked": marked, "unread": 0})
