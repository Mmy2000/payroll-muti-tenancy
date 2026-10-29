"""Leave: the client's leave types, requests for days away, and the yearly balance.

A request counts the working days in its range (weekly days off and public holidays are free).
Leave of a type that `uses_annual_balance` may not take more days than are left in the year:
the employee's `annual_leave_days` (pay in effect on the first day) less what was approved.
PayRole kept running totals on each row (`Pfg1.dr1/dr2`); here the balance is counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.core.history import in_effect
from apps.employees.services import get_employee
from apps.notifications import events

from . import approvals
from .domain.leave import Balance, leave_days
from .models import LeaveRequest, LeaveType, RequestStatus
from .selectors import overlapping_leave, working_day_test

REQUEST, APPROVE = "attendance.leave.request", "attendance.leave.approve"
MANAGE_TYPES = "attendance.leave_type.manage"


def _invalid(fields: dict) -> ValidationError:
    return ValidationError(_("Please correct the highlighted fields."), fields=fields)


# --- leave types ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaveTypeInput:
    code: int
    name: str
    paid: bool = True
    uses_annual_balance: bool = False


def save_leave_type(data: LeaveTypeInput, *, type_id: int | None = None,
                    actor=None) -> LeaveType:
    if actor is not None:
        actor.require(MANAGE_TYPES)
    name = data.name.strip()
    with transaction.atomic():
        leave_type = LeaveType() if type_id is None else LeaveType.objects.filter(
            pk=type_id).select_for_update().first()
        if leave_type is None:
            raise NotFound(_("Not found."))
        others = LeaveType.objects.exclude(pk=leave_type.pk)
        errors = {}
        if not name:
            errors["name"] = [_("Enter a name.")]
        elif others.filter(name=name).exists():
            errors["name"] = [_("Another leave type has this name.")]
        if others.filter(code=data.code).exists():
            errors["code"] = [_("Another leave type has this code.")]
        if errors:
            raise _invalid(errors)
        leave_type.code, leave_type.name = data.code, name
        leave_type.paid, leave_type.uses_annual_balance = data.paid, data.uses_annual_balance
        leave_type.updated_by = getattr(actor, "user", None)
        leave_type.save()
    return leave_type


def set_leave_type_active(type_id: int, active: bool, *, actor=None) -> LeaveType:
    if actor is not None:
        actor.require(MANAGE_TYPES)
    leave_type = LeaveType.objects.filter(pk=type_id).first()
    if leave_type is None:
        raise NotFound(_("Not found."))
    leave_type.is_active = active
    leave_type.save(update_fields=["is_active", "updated_at"])
    return leave_type


def seed_leave_types(**_values) -> None:
    """A new client's starting list (apps.core.seeding), in the client's language."""
    if LeaveType.objects.exists():
        return
    for code, name, paid, balance in ((1, _("Annual leave"), True, True),
                                      (2, _("Sick leave"), True, False),
                                      (3, _("Unpaid leave"), False, False)):
        LeaveType.objects.create(code=code, name=name, paid=paid, uses_annual_balance=balance)


# --- the balance ---------------------------------------------------------------------------


def balance(employee, year: int) -> Balance:
    """Days counted against the annual balance in `year` (by the request's first day)."""
    pay = in_effect(employee.pay_history.all(), max(date(year, 1, 1), employee.hired_on))
    used = (LeaveRequest.objects.filter(employee=employee, leave_type__uses_annual_balance=True,
                                        start_date__year=year)
            .values("status").annotate(days=Sum("days")))
    by_status = {row["status"]: row["days"] for row in used}
    return Balance(entitled=pay.annual_leave_days if pay else 0,
                   taken=by_status.get(RequestStatus.APPROVED, 0),
                   requested=by_status.get(RequestStatus.PENDING, 0))


def _check_balance(request: LeaveRequest) -> None:
    if not request.leave_type.uses_annual_balance:
        return
    left = balance(request.employee, request.start_date.year)
    if not left.allows(request.days):
        raise DomainError(
            _("Only %(left)s days of annual leave are left this year; this request needs "
              "%(days)s.") % {"left": left.remaining, "days": request.days},
            code="ATTENDANCE_LEAVE_BALANCE")


# --- requests ------------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaveRequestInput:
    employee_id: int
    leave_type_id: int
    start_date: date
    end_date: date
    reason: str = ""


def _check_request(data: LeaveRequestInput, employee, leave_type) -> int:
    """The number of leave days, or the reasons the request can't be made."""
    errors = {}
    if leave_type is None:
        errors["leave_type_id"] = [_("Choose an active leave type.")]
    if data.end_date < data.start_date:
        errors["end_date"] = [_("Must not be before the first day.")]
    elif leave_type is not None and leave_type.uses_annual_balance and (
            data.start_date.year != data.end_date.year):
        errors["end_date"] = [_("Annual leave can't run into the next year; make two requests.")]
    elif data.start_date < employee.hired_on or (
            employee.left_on is not None and data.end_date > employee.left_on):
        errors["start_date"] = [_("The employee isn't employed on all these days.")]
    elif overlapping_leave(employee.pk, data.start_date, data.end_date).exists():
        errors["start_date"] = [_("Another request already covers some of these days.")]
    if errors:
        raise _invalid(errors)
    locks.ensure_open(employee.pk, data.start_date, data.end_date)
    days = leave_days(data.start_date, data.end_date, working_day_test(employee))
    if days == 0:
        raise _invalid({"end_date": [_("These are all days off or holidays: no leave is "
                                       "needed.")]})
    return days


def request_leave(data: LeaveRequestInput, *, approve: bool = False, actor=None,
                  by=None) -> LeaveRequest:
    """A new request; `approve` also approves it at once (for members who may). `by`: who
    asked, when the caller is trusted (the mobile app: the employee's own login)."""
    with transaction.atomic():
        employee = get_employee(data.employee_id, actor, REQUEST, lock=True)
        if actor is not None:
            actor.require(REQUEST, branch=employee.branch_id)
            if approve:
                actor.require(APPROVE, branch=employee.branch_id)
        leave_type = LeaveType.objects.filter(pk=data.leave_type_id, is_active=True).first()
        days = _check_request(data, employee, leave_type)
        request = LeaveRequest.objects.create(
            employee=employee, leave_type=leave_type, start_date=data.start_date,
            end_date=data.end_date, days=days, reason=data.reason.strip(),
            created_by=getattr(actor, "user", None))
        if approve:
            approvals.decide(request, approvals.APPROVE, actor=actor,
                             before_approve=_check_balance)
            events.leave_entered_approved(request, by=by or actor)
        else:
            events.leave_requested(request, by=by or actor)
    return request


def decide_leave(request_id: int, move: str, *, note: str = "", actor=None,
                 by=None) -> LeaveRequest:
    """Approve, reject or cancel; refused when an approved payroll covers the leave's days."""
    with transaction.atomic():
        employee_id = LeaveRequest.objects.filter(pk=request_id).values_list(
            "employee_id", flat=True).first()
        if employee_id is None:
            raise NotFound(_("Not found."))
        # Lock the employee, then the request: two decisions can't both pass the same check.
        employee = get_employee(employee_id, actor, APPROVE, lock=True)
        if actor is not None:
            actor.require(APPROVE, branch=employee.branch_id)
        request = (LeaveRequest.objects.select_for_update(of=("self",))
                   .select_related("employee", "leave_type").get(pk=request_id))
        locks.ensure_open(employee.pk, request.start_date, request.end_date)
        approvals.decide(request, move, actor=actor, note=note, before_approve=_check_balance)
        events.leave_decided(request, move, by=by or actor)
        return request
