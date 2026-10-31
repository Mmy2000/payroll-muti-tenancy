"""An employee's trip: opened by checking in, fed by the phone, closed by checking out."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.attendance.models import Punch
from apps.employees.models import Employee

from ..contract import AppError
from ..domain.geo import distance_m
from ..models import EndReason, TrackPoint, TrackSession
from ..selectors import TRACK_MAX_SESSION_HOURS


def close_stale(employee: Employee | None = None) -> int:
    limit = timezone.now() - timedelta(hours=TRACK_MAX_SESSION_HOURS)
    sessions = TrackSession.objects.filter(is_active=True, started_at__lt=limit)
    if employee is not None:
        sessions = sessions.filter(employee=employee)
    closed = 0
    for session in sessions:
        session.is_active, session.end_reason = False, EndReason.TIMEOUT
        session.ended_at = session.started_at + timedelta(hours=TRACK_MAX_SESSION_HOURS)
        session.save(update_fields=["is_active", "end_reason", "ended_at", "updated_at"])
        closed += 1
    return closed


def start_session(employee: Employee, check_in: Punch, device_id: str = "",
                  app_version: str = "") -> TrackSession:
    now = timezone.now()
    TrackSession.objects.filter(employee=employee, is_active=True).update(
        is_active=False, ended_at=now, end_reason=EndReason.TIMEOUT)
    return TrackSession.objects.create(employee=employee, branch=employee.branch,
                                       check_in=check_in, started_at=check_in.at,
                                       device_id=device_id, app_version=app_version)


def stop_session(employee: Employee, reason: str, *, check_out: Punch | None = None
                 ) -> TrackSession | None:
    session = TrackSession.objects.filter(employee=employee, is_active=True).first()
    if session is None:
        return None
    session.is_active, session.end_reason = False, reason
    session.ended_at = check_out.at if check_out else timezone.now()
    session.check_out = check_out
    session.save(update_fields=["is_active", "end_reason", "ended_at", "check_out",
                                "updated_at"])
    return session


def add_points(employee: Employee, session_id: int | None, points: list[dict]
               ) -> tuple[int, TrackSession]:
    """Store a batch (points already stored at the same time are skipped) and measure the
    route again in time order (PayRole added each batch from its newest point, so a late batch
    lengthened the route)."""
    with transaction.atomic():
        if session_id is not None:
            session = (TrackSession.objects.select_for_update()
                       .filter(pk=session_id, employee=employee).first())
        else:
            close_stale(employee)
            session = (TrackSession.objects.select_for_update()
                       .filter(employee=employee, is_active=True).first())
        if session is None:
            raise AppError("no_active_session", tracking=False)
        if not session.is_active:
            raise AppError("session_closed", tracking=False)
        points = sorted(points, key=lambda p: p["recorded_at"])
        stored = set(session.points.filter(
            recorded_at__range=(points[0]["recorded_at"], points[-1]["recorded_at"]))
            .values_list("recorded_at", flat=True))
        fresh, seen = [], set(stored)
        for point in points:
            if point["recorded_at"] not in seen:
                seen.add(point["recorded_at"])
                fresh.append(TrackPoint(session=session, **point))
        TrackPoint.objects.bulk_create(fresh, ignore_conflicts=True)
        route = list(session.points.order_by("recorded_at").values_list("latitude",
                                                                       "longitude"))
        total = sum(distance_m(*a, *b) for a, b in zip(route, route[1:], strict=False))
        session.points_count = len(route)
        session.total_distance_m = Decimal(str(round(total, 2)))
        session.save(update_fields=["points_count", "total_distance_m", "updated_at"])
    return len(fresh), session


def active_session(employee: Employee) -> TrackSession | None:
    close_stale(employee)
    return TrackSession.objects.filter(employee=employee, is_active=True).first()
