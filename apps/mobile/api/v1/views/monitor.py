"""Following employees' routes, for those allowed to."""

from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.response import Response

from .... import contract, selectors
from ....contract import AppError
from ....models import TrackSession
from ....services import tracking
from .. import serializers as s
from .attendance import parse_day
from .base import MONITOR, AppView, CanMonitor


class MonitorView(AppView):
    permission_classes = [CanMonitor]

    def sessions(self):
        rows = TrackSession.objects.select_related("employee", "branch")
        allowed = self.request._request.actor.branch_ids(MONITOR)
        return rows if allowed is None else rows.filter(branch_id__in=allowed)


class MonitorLiveView(MonitorView):
    def get(self, request):
        tracking.close_stale()
        rows = []
        now = timezone.now()
        for session in self.sessions().filter(is_active=True).order_by("-started_at"):
            last = session.points.order_by("-recorded_at").first()
            if last is not None:
                position = {"lat": float(last.latitude), "lng": float(last.longitude),
                            "at": timezone.localtime(last.recorded_at).strftime("%H:%M"),
                            "battery": last.battery, "source": "track"}
                silent = int((now - last.recorded_at).total_seconds() // 60)
            elif session.check_in and session.check_in.latitude is not None:
                position = {"lat": float(session.check_in.latitude),
                            "lng": float(session.check_in.longitude),
                            "at": timezone.localtime(session.check_in.at).strftime("%H:%M"),
                            "battery": None, "source": "check_in"}
                silent = None
            else:
                position, silent = None, None
            rows.append({"session": s.monitor_session(session, request), "position": position,
                         "silent_minutes": silent})
        return Response({"interval_seconds": selectors.TRACK_INTERVAL_SECONDS, "rows": rows})


class MonitorSessionsView(MonitorView):
    def get(self, request):
        rows = self.sessions()
        key = request.GET.get("key", "").strip()
        if key:
            rows = rows.filter(employee__name__icontains=key)
        start, end = parse_day(request.GET.get("from", "")), parse_day(request.GET.get("to", ""))
        if start:
            rows = rows.filter(started_at__date__gte=start)
        if end:
            rows = rows.filter(started_at__date__lte=end)
        if request.GET.get("active") == "1":
            rows = rows.filter(is_active=True)
        rows = rows.order_by("-started_at")
        page = Paginator(rows, 20).get_page(request.GET.get("page"))
        totals = rows.aggregate(count=Count("pk"), active=Count("pk", filter=Q(is_active=True)),
                                distance=Sum("total_distance_m"), points=Sum("points_count"))
        return Response({
            "page": page.number, "pages": page.paginator.num_pages,
            "has_next": page.has_next(),
            "totals": {"count": totals["count"], "active": totals["active"],
                       "distance_m": float(totals["distance"] or 0),
                       "points": totals["points"] or 0},
            "results": [s.monitor_session(row, request) for row in page.object_list]})


class MonitorSessionView(MonitorView):
    def get(self, request, session_id):
        session = self.sessions().filter(pk=session_id).first()
        if session is None:
            raise AppError("not_found", detail=contract.MESSAGES["session_not_found"])
        route = [{"lat": float(p.latitude), "lng": float(p.longitude),
                  "at": timezone.localtime(p.recorded_at).strftime("%Y-%m-%d %H:%M:%S"),
                  "accuracy": float(p.accuracy_m) if p.accuracy_m is not None else None,
                  "battery": p.battery, "is_mock": p.is_mock}
                 for p in session.points.order_by("recorded_at")]

        def end(punch):
            if punch is None or punch.latitude is None:
                return None
            return {"lat": float(punch.latitude), "lng": float(punch.longitude),
                    "at": timezone.localtime(punch.at).strftime("%Y-%m-%d %H:%M")}

        return Response({"session": s.monitor_session(session, request), "route": route,
                         "endpoints": {"check_in": end(session.check_in),
                                       "check_out": end(session.check_out)},
                         "mock_count": sum(1 for p in route if p["is_mock"]),
                         "retention_days": selectors.TRACK_RETENTION_DAYS})
