"""Hourly leave ("إذن"): a few hours away within a work day, not deducted from pay up to the
employee's monthly allowance (Compensation.permission_hours, PayRole: `Pfe1.perm`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.core.errors import DomainError, NotFound, ValidationError
from apps.core.history import in_effect
from apps.employees.services import get_employee

from . import approvals
from .domain.leave import span_minutes
from .models import HourlyLeave, RequestStatus
from .selectors import active_requests

REQUEST, APPROVE = "attendance.hourly.request", "attendance.hourly.approve"
MAX_MINUTES = 12 * 60


@dataclass(frozen=True)
class HourlyLeaveInput:
    employee_id: int
    work_date: date
    starts_at: time
    ends_at: time
    reason: str = ""


def _minutes_used(request: HourlyLeave) -> int:
    month = HourlyLeave.objects.filter(
        employee=request.employee, status=RequestStatus.APPROVED,
        work_date__year=request.work_date.year, work_date__month=request.work_date.month)
    return month.aggregate(total=Sum("minutes"))["total"] or 0


def _check_allowance(request: HourlyLeave) -> None:
    pay = in_effect(request.employee.pay_history.all(), request.work_date)
    allowed = int((pay.permission_hours if pay else 0) * 60)
    used = _minutes_used(request)
    if used + request.minutes > allowed:
        raise DomainError(
            _("This month's allowance is %(allowed)s minutes and %(used)s are used; this "
              "request needs %(minutes)s.")
            % {"allowed": allowed, "used": used, "minutes": request.minutes},
            code="ATTENDANCE_HOURLY_ALLOWANCE")


def record_hourly_leave(data: HourlyLeaveInput, *, approve: bool = False,
                        actor=None) -> HourlyLeave:
    with transaction.atomic():
        employee = get_employee(data.employee_id, actor, REQUEST, lock=True)
        if actor is not None:
            actor.require(REQUEST, branch=employee.branch_id)
            if approve:
                actor.require(APPROVE, branch=employee.branch_id)
        minutes = span_minutes(data.starts_at, data.ends_at)
        errors = {}
        if minutes > MAX_MINUTES:
            errors["ends_at"] = [_("Hourly leave is for part of a day; use leave for more.")]
        if not (employee.hired_on <= data.work_date
                and (employee.left_on is None or data.work_date <= employee.left_on)):
            errors["work_date"] = [_("The employee isn't employed on that day.")]
        elif active_requests(HourlyLeave, employee.pk).filter(work_date=data.work_date).exists():
            errors["work_date"] = [_("There is already hourly leave on that day.")]
        if errors:
            raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
        request = HourlyLeave.objects.create(
            employee=employee, work_date=data.work_date, starts_at=data.starts_at,
            ends_at=data.ends_at, minutes=minutes, reason=data.reason.strip(),
            created_by=getattr(actor, "user", None))
        if approve:
            approvals.decide(request, approvals.APPROVE, actor=actor,
                             before_approve=_check_allowance)
    return request


def decide_hourly_leave(request_id: int, move: str, *, note: str = "",
                        actor=None) -> HourlyLeave:
    with transaction.atomic():
        employee_id = HourlyLeave.objects.filter(pk=request_id).values_list(
            "employee_id", flat=True).first()
        if employee_id is None:
            raise NotFound(_("Not found."))
        # Lock the employee, then the request: two decisions can't both pass the same check.
        employee = get_employee(employee_id, actor, APPROVE, lock=True)
        if actor is not None:
            actor.require(APPROVE, branch=employee.branch_id)
        request = (HourlyLeave.objects.select_for_update(of=("self",))
                   .select_related("employee").get(pk=request_id))
        return approvals.decide(request, move, actor=actor, note=note,
                                before_approve=_check_allowance)
