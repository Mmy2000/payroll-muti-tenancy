"""The phone's trip points."""

from __future__ import annotations

from rest_framework.response import Response

from ....services import tracking
from .. import serializers as s
from .base import AppView, valid


class TrackBatchView(AppView):
    def post(self, request):
        person = self.employee()
        data = valid(s.TrackBatchSerializer, request.data)
        points = [dict(p) for p in data["points"]]
        saved, session = tracking.add_points(person, data["session_id"], points)
        return Response({"saved": saved, "received": len(points),
                         "session": s.session(session), "tracking": True})


class TrackStopView(AppView):
    def post(self, request):
        session = tracking.stop_session(self.employee(), "manual")
        return Response({"session": s.session(session), "tracking": False})
