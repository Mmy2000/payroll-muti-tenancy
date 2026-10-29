"""Hourly leave ("إذن"): a few hours away within a work day, not deducted from pay up to the
employee's monthly allowance (Compensation.permission_hours, PayRole: `Pfe1.perm`).

An employee may have several in a day, as long as they don't overlap; a span may go past
midnight. `record_hourly_leave_for_group` enters the same spans for many employees at once,
with a preview (apps/core/bulk.py): each one is still checked on its own, by the same function.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from functools import partial

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.core import bulk, locks
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.core.history import in_effect
from apps.employees.services import get_employee
from apps.employees.targets import Group, resolve_group
from apps.notifications import events

from . import approvals
from .domain.days import Status
from .domain.leave import span_minutes, spans_overlap
from .models import HourlyLeave, RequestStatus
from .selectors import active_requests, evaluate

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


def _allowance(employee, day: date) -> int:
    pay = in_effect(employee.pay_history.all(), day)
    return int((pay.permission_hours if pay else 0) * 60)


def _check_allowance(request: HourlyLeave) -> None:
    allowed = _allowance(request.employee, request.work_date)
    used = _minutes_used(request)
    if used + request.minutes > allowed:
        raise DomainError(
            _("This month's allowance is %(allowed)s minutes and %(used)s are used; this "
              "request needs %(minutes)s.")
            % {"allowed": allowed, "used": used, "minutes": request.minutes},
            code="ATTENDANCE_HOURLY_ALLOWANCE")


def _clashes(employee_id: int, work_date: date, starts_at: time, ends_at: time) -> bool:
    return any(spans_overlap((starts_at, ends_at), (row.starts_at, row.ends_at))
               for row in active_requests(HourlyLeave, employee_id).filter(work_date=work_date))


def record_hourly_leave(data: HourlyLeaveInput, *, approve: bool = False,
                        actor=None) -> HourlyLeave:
    with transaction.atomic():
        employee = get_employee(data.employee_id, actor, REQUEST, lock=True)
        if actor is not None:
            actor.require(REQUEST, branch=employee.branch_id)
            if approve:
                actor.require(APPROVE, branch=employee.branch_id)
        locks.ensure_open(employee.pk, data.work_date)
        minutes = span_minutes(data.starts_at, data.ends_at)
        errors = {}
        if minutes > MAX_MINUTES:
            errors["ends_at"] = [_("Hourly leave is for part of a day; use leave for more.")]
        if not (employee.hired_on <= data.work_date
                and (employee.left_on is None or data.work_date <= employee.left_on)):
            errors["work_date"] = [_("The employee isn't employed on that day.")]
        elif _clashes(employee.pk, data.work_date, data.starts_at, data.ends_at):
            errors["starts_at"] = [_("This overlaps other hourly leave on that day.")]
        if errors:
            raise ValidationError(_("Please correct the highlighted fields."), fields=errors)
        request = HourlyLeave.objects.create(
            employee=employee, work_date=data.work_date, starts_at=data.starts_at,
            ends_at=data.ends_at, minutes=minutes, reason=data.reason.strip(),
            created_by=getattr(actor, "user", None))
        if approve:
            approvals.decide(request, approvals.APPROVE, actor=actor,
                             before_approve=_check_allowance)
        events.hourly_leave_entered(request, by=actor)
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
        locks.ensure_open(employee.pk, request.work_date)
        approvals.decide(request, move, actor=actor, note=note,
                         before_approve=_check_allowance)
        if move == approvals.CANCEL:
            events.hourly_leave_cancelled(request, by=actor)
        return request


# --- for a group -----------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupHourlyLeaveInput:
    group: Group
    work_date: date
    spans: tuple[tuple[time, time], ...]  # (from, to), one or more
    reason: str = ""


def _check_spans(spans) -> None:
    errors = {}
    if not spans:
        errors["spans"] = [_("Enter at least one time span.")]
    for index, (start, end) in enumerate(spans):
        if start == end:
            errors[f"spans.{index}"] = [_("The end must be another time than the start.")]
        elif any(spans_overlap((start, end), other) for other in spans[:index]):
            errors[f"spans.{index}"] = [_("This overlaps an earlier span.")]
    if errors:
        raise ValidationError(_("Please correct the highlighted fields."), fields=errors)


def _warnings(employee, work_date: date, minutes: int, approve: bool):
    """What the preview should say about one employee's span, though it can be saved."""

    def warn():
        day = evaluate([employee], work_date, work_date)[employee.pk][0]
        if day.status in (Status.DAY_OFF, Status.HOLIDAY):
            yield _("Not a working day for them (%(what)s).") % {
                "what": day.label or _("day off")}
        elif day.status == Status.LEAVE:
            yield _("On leave that day (%(what)s).") % {"what": day.label}
        if not approve:
            allowed = _allowance(employee, work_date)
            used = _minutes_used(HourlyLeave(employee=employee, work_date=work_date))
            if used + minutes > allowed:
                yield _("Over this month's allowance (%(allowed)s minutes, %(used)s used): "
                        "approval will be refused.") % {"allowed": allowed, "used": used}

    return warn


def record_hourly_leave_for_group(data: GroupHourlyLeaveInput, *, approve: bool = False,
                                  save: bool = False, skip_failed: bool = False,
                                  actor=None) -> bulk.Outcome:
    """The same spans for every employee of the group: previewed (`save` false) or saved."""
    if actor is not None:
        actor.require(REQUEST)
        if approve:
            actor.require(APPROVE)
    _check_spans(data.spans)
    with transaction.atomic():
        people = resolve_group(data.group, on=data.work_date, actor=actor, permission=REQUEST)
        items = [
            bulk.Item(employee, f"{start:%H:%M}–{end:%H:%M}",
                      partial(record_hourly_leave, HourlyLeaveInput(
                          employee.pk, data.work_date, start, end, data.reason),
                          approve=approve, actor=actor),
                      warn=_warnings(employee, data.work_date, span_minutes(start, end),
                                     approve))
            for employee in people for start, end in data.spans]
        return bulk.run(items, save=save, skip_failed=skip_failed)
