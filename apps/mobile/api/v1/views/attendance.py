"""Punching, today and the history."""

from __future__ import annotations

from datetime import date

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from ....services import punches as punches_services
from ....services import tracking
from .. import serializers as s
from .base import AppView, valid
from .profile import today


class PunchView(AppView):
    def post(self, request):
        data = valid(s.PunchSerializer, request.data)
        person = self.employee(status_code=400)
        record, session = punches_services.punch(person, punches_services.PunchInput(
            direction=int(data["status"]), latitude=data["latitude"],
            longitude=data["longitude"], device_id=data["device_id"],
            app_version=data["app_version"], tracking_enabled=data["tracking_enabled"],
            proof=data["biometric"]))
        return Response({"attendance": s.attendance(record, int(data["status"])),
                         "session": s.session(session),
                         "tracking": bool(session and session.is_active)},
                        status=status.HTTP_201_CREATED)


class TodayView(AppView):
    def get(self, request):
        person = self.employee()
        day, punches = today(person)
        records = s.attendance_list(punches)
        session = tracking.active_session(person)
        return Response({
            "date": day.isoformat(),
            "check_in": next((r for r in records if r["status"] == 0), None),
            "check_out": next((r for r in reversed(records) if r["status"] == 1), None),
            "records": records, "tracking": session is not None,
            "session": s.session(session)})


def parse_day(text: str):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


class HistoryView(AppView):
    def get(self, request):
        person = self.employee()
        punches = person.punches.order_by("-at")
        start, end = parse_day(request.GET.get("from", "")), parse_day(request.GET.get("to", ""))
        zone = timezone.get_current_timezone()
        if start:
            punches = punches.filter(at__date__gte=start)
        if end:
            punches = punches.filter(at__date__lte=end)
        rows = list(punches[:500])
        by_day: dict = {}
        for punch in sorted(rows, key=lambda p: p.at):
            by_day.setdefault(punch.at.astimezone(zone).date(), []).append(punch)
        directions = {}
        for day_punches in by_day.values():
            directions.update(punches_services.directions(day_punches))
        return Response([s.attendance(p, directions[p.pk]) for p in rows])
