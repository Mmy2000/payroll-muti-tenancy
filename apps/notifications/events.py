"""The events members are told about (PayRole Notif/signals.py), called by the services where
they happen, inside their transaction. Each says who is told and in which words.

The employee is told through their own login (Employee.member); a request to decide goes to
the members who may decide it in the employee's branch.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from .models import Kind
from .services import notify


def _member(employee):
    member = getattr(employee, "member", None)
    return member if member is not None and member.status == "active" else None


def _deciders(permission: str, employee):
    from apps.iam.authz import members_who_can

    return list(members_who_can(permission, employee.branch_id))


def _range(request) -> str:
    if request.start_date == request.end_date:
        return _("on %(day)s") % {"day": request.start_date}
    return _("%(days)s days from %(start)s to %(end)s") % {
        "days": request.days, "start": request.start_date, "end": request.end_date}


# --- leave -----------------------------------------------------------------------------------


def leave_requested(request, *, by=None) -> None:
    """A request waiting for approval: its deciders are told when the employee asked; the
    employee is told when someone asked for them."""
    employee = request.employee
    own = by is not None and _member(employee) is not None and \
        getattr(by, "membership", by).pk == employee.member_id
    if own:
        notify(_deciders("attendance.leave.approve", employee), Kind.LEAVE_REQUEST,
               lambda: _("Leave request from %(name)s") % {"name": employee.name},
               lambda: _range(request), url="/attendance/leave/", by=by)
    else:
        notify([_member(employee)], Kind.LEAVE_ADDED,
               _("A leave request was entered for you, waiting for approval"),
               lambda: _range(request), by=by)


def leave_decided(request, move: str, *, by=None) -> None:
    employee = request.employee
    if move == "approve":
        kind, title = Kind.LEAVE_APPROVED, _("Your leave request was approved")
    elif move == "reject":
        kind, title = Kind.LEAVE_REJECTED, _("Your leave request was rejected")
    elif getattr(by, "membership", by) is not None and \
            getattr(by, "membership", by).pk == employee.member_id:
        notify(_deciders("attendance.leave.approve", employee), Kind.LEAVE_WITHDRAWN,
               lambda: _("%(name)s withdrew their leave request") % {"name": employee.name},
               lambda: _range(request), url="/attendance/leave/", by=by)
        return
    else:
        kind, title = Kind.LEAVE_CANCELLED, _("Your leave was cancelled")
    notify([_member(employee)], kind, title, lambda: _range(request), by=by)


def leave_entered_approved(request, *, by=None) -> None:
    notify([_member(request.employee)], Kind.LEAVE_ADDED,
           _("Approved leave was entered for you"), lambda: _range(request), by=by)


def hourly_leave_entered(request, *, by=None) -> None:
    notify([_member(request.employee)], Kind.PERMISSION_ADDED,
           _("Hourly leave was entered for you"),
           lambda: _("On %(day)s from %(start)s to %(end)s") % {
               "day": request.work_date, "start": f"{request.starts_at:%H:%M}",
               "end": f"{request.ends_at:%H:%M}"}, by=by)


def hourly_leave_cancelled(request, *, by=None) -> None:
    notify([_member(request.employee)], Kind.PERMISSION_CANCELLED,
           _("Your hourly leave was cancelled"),
           lambda: _("On %(day)s") % {"day": request.work_date}, by=by)


# --- pay -------------------------------------------------------------------------------------


def adjustment_approved(batch, *, by=None) -> None:
    title = (_("An incentive was given to you") if batch.kind == "incentive"
             else _("A penalty was recorded for you"))
    for row in batch.rows.select_related("employee__member"):
        notify([_member(row.employee)], Kind.MOVEMENT, title,
               lambda row=row: _("The amount %(amount)s on %(day)s") % {
                   "amount": row.amount, "day": row.date}, by=by)


def advance_given(advance, *, by=None) -> None:
    notify([_member(advance.employee)], Kind.MOVEMENT, _("A salary advance was recorded"),
           lambda: _("The amount %(amount)s on %(day)s") % {
               "amount": advance.amount, "day": advance.date}, by=by)


def loan_granted(loan, installments: int, *, by=None) -> None:
    notify([_member(loan.employee)], Kind.MOVEMENT, _("A loan was recorded"),
           lambda: _("The amount %(amount)s on %(day)s, over %(months)s months") % {
               "amount": loan.amount, "day": loan.granted_on, "months": installments}, by=by)


def pay_paid(run, *, by=None) -> None:
    for slip in run.payslips.select_related("employee__member"):
        notify([_member(slip.employee)], Kind.SALARY_PAID, _("Your pay was paid"),
               lambda slip=slip: _("The period from %(start)s to %(end)s — net %(net)s") % {
                   "start": run.period.start, "end": run.period.end, "net": slip.net}, by=by)
