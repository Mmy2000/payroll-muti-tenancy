"""The browser's API for notifications (the bell, static/core/js/bell.js): GET the latest and
what needs attention (?count=1: the unread count only), POST <id>/read/, POST read-all/."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.iam.catalog import AUTHENTICATED

from . import attention, services
from .present import item

LATEST = 20


class NotificationsView(APIView):
    required_permissions = {"GET": AUTHENTICATED}

    def get(self, request):
        member = request.actor.membership
        unread = services.unread_count(member)
        if request.GET.get("count") == "1":
            return Response({"unread": unread})
        rows = services.for_member(member).order_by("-id")[:LATEST]
        return Response({"unread": unread, "results": [item(r) for r in rows],
                         "attention": attention.waiting(request.actor)})


class ReadView(APIView):
    required_permissions = {"POST": AUTHENTICATED}

    def post(self, request, pk):
        services.mark_read(request.actor.membership, [pk])
        return Response({"unread": services.unread_count(request.actor.membership)})


class ReadAllView(APIView):
    required_permissions = {"POST": AUTHENTICATED}

    def post(self, request):
        marked = services.mark_read(request.actor.membership)
        return Response({"marked": marked, "unread": 0})


urlpatterns = [
    path("", NotificationsView.as_view(), name="notifications-api"),
    path("<int:pk>/read/", ReadView.as_view(), name="notifications-read"),
    path("read-all/", ReadAllView.as_view(), name="notifications-read-all"),
]
