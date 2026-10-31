"""The bell, in the app."""

from __future__ import annotations

from rest_framework.response import Response

from apps.notifications import selectors as notifications_selectors
from apps.notifications import services as notifications

from .... import contract
from .. import serializers as s
from .base import AppView, valid


class NotificationsView(AppView):
    def get(self, request):
        before = request.GET.get("before", "")
        rows = notifications_selectors.newest_for(
            self.member, unread_only=request.GET.get("unread") == "1",
            before=int(before) if before.isdigit() else None)
        items = list(rows[:notifications.PAGE])
        return Response({
            "unread": notifications_selectors.unread_count(self.member),
            "items": [{"id": n.pk, "kind": n.kind, "title": n.title, "body": n.body,
                       "read": n.read_at is not None, "created_at": contract.moment(
                           n.created_at)} for n in items],
            "has_more": len(items) == notifications.PAGE})


class NotificationsReadView(AppView):
    def post(self, request):
        data = valid(s.NotificationsReadSerializer, request.data)
        marked = notifications.mark_read(self.member, data["ids"] or None)
        return Response({"marked": marked,
                         "unread": notifications_selectors.unread_count(self.member)})
