"""Leave from the app: a leave request of the annual type, with this system's balance and
approval, and the app's own messages."""

from __future__ import annotations

from datetime import date

from apps.attendance.models import LeaveRequest, RequestStatus
from apps.attendance.services import leave as leave_services
from apps.core.errors import AppError as ServiceError
from apps.employees.models import Employee

from ..contract import MESSAGES, AppError
from ..selectors import annual_type, balance, switched_on


def ask_leave(employee: Employee, member, start: date, end: date) -> LeaveRequest:
    """A request from the app is refused up front when the balance (waiting requests counted)
    can't cover it, as PayRole's was; the screens check it at approval."""
    from apps.attendance.domain.leave import leave_days
    from apps.attendance.selectors import working_day_test

    if not switched_on("leave"):
        raise AppError("leave_off", status=403)  # nobody could see or decide it
    leave_type = annual_type()
    days = leave_days(start, end, working_day_test(employee))
    left = balance(employee, start.year)
    if days > left["remaining"]:
        raise AppError("insufficient_balance", detail=MESSAGES["insufficient_balance"].format(
            left=left["remaining"], days=days))
    try:
        return leave_services.request_leave(leave_services.LeaveRequestInput(
            employee_id=employee.pk, leave_type_id=leave_type.pk, start_date=start,
            end_date=end), by=member)
    except ServiceError as error:
        raise AppError(error.code.lower(), detail=_first_message(error)) from None


def _first_message(error: ServiceError) -> str:
    for messages in error.fields.values():
        if messages:
            return str(messages[0])
    return error.message


def withdraw_leave(employee: Employee, member, pk: int) -> None:
    request = LeaveRequest.objects.filter(pk=pk, employee=employee).first()
    if request is None or request.status not in (RequestStatus.PENDING,
                                                 RequestStatus.APPROVED):
        raise AppError("not_found")
    if request.status == RequestStatus.APPROVED:
        raise AppError("already_accepted")
    try:
        leave_services.decide_leave(request.pk, "cancel", by=member)
    except ServiceError as error:
        raise AppError(error.code.lower(), detail=error.message) from None
