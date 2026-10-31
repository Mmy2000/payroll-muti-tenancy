"""Punching from the app (docs/mobile-api.md), in PayRole's order of checks and with its messages
(apps/mobile/contract.py).

A punch is an attendance punch (source "mobile", with what the employee pressed and where), judged
like the device's. Its day is the employee's work day: a night shift's check-out after midnight
belongs to the day it started (PayRole refused it). The fingerprint proof, GPS tracking and the
geofence are the client's features.

The app acts for the employee on their own records only, so the services here are trusted callers
of the attendance services (no actor), and say who asked (`by`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.attendance.models import Punch, PunchSource
from apps.core.errors import AppError as ServiceError
from apps.employees.models import Employee

from ..contract import AppError, duplicate
from ..domain.geo import distance_m
from ..models import EndReason, TrackSession
from ..selectors import day_punches, switched_on, work_day
from .biometrics import verify_proof
from .tracking import start_session, stop_session

# --- work days and punches -------------------------------------------------------------------


def directions(punches: list[Punch]) -> dict[int, int]:
    """In (0) or out (1) for each punch: what the employee pressed, else first in, then out."""
    return {p.pk: p.direction if p.direction is not None else (0 if index == 0 else 1)
            for index, p in enumerate(punches)}


def directions_by_day(punches: list[Punch]) -> dict[int, int]:
    """`directions` of punches from several days, each day on its own."""
    zone = timezone.get_current_timezone()
    by_day: dict = {}
    for punch in sorted(punches, key=lambda p: p.at):
        by_day.setdefault(punch.at.astimezone(zone).date(), []).append(punch)
    found = {}
    for day in by_day.values():
        found.update(directions(day))
    return found


# --- the fingerprint proof -------------------------------------------------------------------


# --- the geofence ----------------------------------------------------------------------------


def _check_area(employee: Employee, latitude, longitude) -> None:
    branch = employee.branch
    if not switched_on("geofence") or branch.latitude is None or branch.longitude is None:
        return
    if latitude is None or longitude is None:
        raise AppError("location_required")
    if distance_m(branch.latitude, branch.longitude, latitude, longitude) > branch.radius_m:
        raise AppError("outside_geofence")


# --- punching --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PunchInput:
    direction: int
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    device_id: str = ""
    app_version: str = ""
    tracking_enabled: bool = False
    proof: dict | None = None


def punch(employee: Employee, data: PunchInput) -> tuple[Punch, TrackSession | None]:
    from apps.core import locks

    with transaction.atomic():
        employee = Employee.objects.select_for_update().select_related("branch").get(
            pk=employee.pk)
        if switched_on("biometric"):
            verify_proof(employee, data.direction, data.device_id, data.proof)
        if data.direction == 0 and switched_on("gps_tracking") and not data.tracking_enabled:
            raise AppError("tracking_required")
        _check_area(employee, data.latitude, data.longitude)
        now = timezone.now()
        today = work_day(employee, now)
        punches = day_punches(employee, today)
        same = [p for p in punches if p.source == PunchSource.MOBILE
                and p.direction == data.direction]
        if same:
            raise duplicate(data.direction, same[0].at)
        if data.direction == 1 and not punches:
            raise AppError("no_check_in")
        try:
            locks.ensure_open(employee.pk, today)
        except ServiceError as error:
            raise AppError(error.code.lower(), detail=error.message) from None
        record = Punch.objects.create(employee=employee, at=now, source=PunchSource.MOBILE,
                                      direction=data.direction, latitude=data.latitude,
                                      longitude=data.longitude)
        if data.direction == 0:
            session = start_session(employee, record, data.device_id, data.app_version)
        else:
            session = stop_session(employee, EndReason.CHECKOUT, check_out=record)
    return record, session


# --- tracking --------------------------------------------------------------------------------


# --- leave -----------------------------------------------------------------------------------


