"""Employees: their card, their pay history and their working hours.

Permissions follow the employee's branch: a member allowed in some branches sees and manages only
the employees of those branches. Pay is a permission of its own (`employees.salary.read` /
`employees.salary.manage`), so a member can keep cards without seeing what anyone earns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.crypto import blind_index, encrypt
from apps.core.errors import DomainError, NotFound, ValidationError, invalid_fields
from apps.iam import services as iam
from apps.iam.models import MembershipStatus

from ..models import Compensation, Employee, PayFrequency, WageType, WorkSchedule
from ..permissions import MANAGE, SALARY_MANAGE
from ..selectors import get_employee, visible_employees
from ..validators import (
    NATIONAL_ID_PURPOSE,
    check_card,
    check_change_date,
    check_pay,
    check_schedule,
    normalize_national_id,
)

logger = logging.getLogger(__name__)

# --- the card ------------------------------------------------------------------------------


@dataclass(frozen=True)
class EmployeeInput:
    code: int
    name: str
    branch_id: int
    hired_on: date
    department_id: int | None = None
    job_title: str = ""
    gender: str = ""
    national_id: str = ""
    birth_date: date | None = None
    phone: str = ""
    email: str = ""
    address: str = ""
    insurance_number: str = ""
    insured_from: date | None = None
    qualification: str = ""
    marital_status: str = ""
    children: int = 0
    military_status: str = ""
    notes: str = ""


def _apply_card(employee: Employee, data: EmployeeInput, actor) -> None:
    national_id = normalize_national_id(data.national_id)
    employee.code = data.code
    employee.name = data.name.strip()
    employee.branch_id = data.branch_id
    employee.department_id = data.department_id
    employee.hired_on = data.hired_on
    for name in ("job_title", "phone", "email", "address", "insurance_number", "qualification",
                 "notes"):
        setattr(employee, name, getattr(data, name).strip())
    for name in ("gender", "birth_date", "insured_from", "marital_status", "children",
                 "military_status"):
        setattr(employee, name, getattr(data, name))
    employee.national_id_encrypted = encrypt(national_id)
    employee.national_id_index = blind_index(national_id, purpose=NATIONAL_ID_PURPOSE)
    employee.updated_by = getattr(actor, "user", None)


# --- pay and hours -------------------------------------------------------------------------


@dataclass(frozen=True)
class CompensationInput:
    effective_from: date | None  # None: from the hiring date (a new employee)
    salary: Decimal
    wage_type: str = WageType.FIXED
    pay_frequency: str = PayFrequency.MONTHLY
    hours_per_day: Decimal = Decimal(8)
    overtime_multiplier: Decimal = Decimal("1.5")
    absence_multiplier: Decimal = Decimal(1)
    holiday_multiplier: Decimal = Decimal(1)
    insured_salary: Decimal | None = None
    annual_leave_days: int = 21
    permission_hours: Decimal = Decimal(0)
    note: str = ""


@dataclass(frozen=True)
class ScheduleInput:
    effective_from: date | None  # None: from the hiring date (a new employee)
    starts_at: time
    ends_at: time
    days_off: list[int] = field(default_factory=list)
    lateness_policy_id: int | None = None
    overtime_policy_id: int | None = None
    early_leave_minutes: int = 0
    note: str = ""


def _new_pay(employee: Employee, data: CompensationInput, actor) -> Compensation:
    values = {name: getattr(data, name) for name in (
        "wage_type", "pay_frequency", "salary", "hours_per_day", "overtime_multiplier",
        "absence_multiplier", "holiday_multiplier", "insured_salary", "annual_leave_days",
        "permission_hours")}
    return Compensation.objects.create(
        employee=employee, effective_from=data.effective_from or employee.hired_on,
        note=data.note.strip(), created_by=getattr(actor, "user", None), **values)


def _new_schedule(employee: Employee, data: ScheduleInput, actor) -> WorkSchedule:
    return WorkSchedule.objects.create(
        employee=employee, effective_from=data.effective_from or employee.hired_on,
        starts_at=data.starts_at, ends_at=data.ends_at, days_off=sorted(set(data.days_off)),
        lateness_policy_id=data.lateness_policy_id, overtime_policy_id=data.overtime_policy_id,
        early_leave_minutes=data.early_leave_minutes, note=data.note.strip(),
        created_by=getattr(actor, "user", None))


def _prefixed(prefix: str, errors: dict) -> dict:
    return {f"{prefix}.{name}": messages for name, messages in errors.items()}


# --- writes --------------------------------------------------------------------------------


def create_employee(data: EmployeeInput, pay: CompensationInput, schedule: ScheduleInput, *,
                    actor=None) -> Employee:
    """A new employee with the pay and hours they start with (from their hiring date)."""
    if actor is not None:
        actor.require(MANAGE, branch=data.branch_id)
        actor.require(SALARY_MANAGE, branch=data.branch_id)
    with transaction.atomic():
        employee = Employee(created_by=getattr(actor, "user", None))
        errors = {**check_card(data, employee), **_prefixed("pay", check_pay(pay)),
                  **_prefixed("schedule", check_schedule(schedule))}
        if errors:
            raise invalid_fields(errors)
        _apply_card(employee, data, actor)
        employee.save()
        _new_pay(employee, pay, actor)
        _new_schedule(employee, schedule, actor)
    return employee


def update_employee(employee_id: int, data: EmployeeInput, *, actor=None) -> Employee:
    with transaction.atomic():
        employee = get_employee(employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
            actor.require(MANAGE, branch=data.branch_id)  # moving to another branch
        errors = check_card(data, employee)
        first_pay = employee.pay_history.order_by("effective_from").first()
        if first_pay is not None and data.hired_on > first_pay.effective_from:
            errors.setdefault("hired_on", [_("Pay is recorded from an earlier date.")])
        if errors:
            raise invalid_fields(errors)
        _apply_card(employee, data, actor)
        employee.save()
    return employee


def change_pay(employee_id: int, data: CompensationInput, *, actor=None) -> Compensation:
    """New pay from a date. Earlier months keep the pay they had."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, SALARY_MANAGE, lock=True)
        if actor is not None:
            actor.require(SALARY_MANAGE, branch=employee.branch_id)
        start = check_change_date(employee, data.effective_from)
        errors = check_pay(data)
        if employee.pay_history.filter(effective_from=start).exists():
            errors["effective_from"] = [_("Pay already changes on this date.")]
        if errors:
            raise invalid_fields(errors)
        return _new_pay(employee, data, actor)


def change_schedule(employee_id: int, data: ScheduleInput, *, actor=None) -> WorkSchedule:
    """New working hours from a date. Earlier days keep the hours they had."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        start = check_change_date(employee, data.effective_from)
        errors = check_schedule(data)
        if employee.schedules.filter(effective_from=start).exists():
            errors["effective_from"] = [_("The hours already change on this date.")]
        if errors:
            raise invalid_fields(errors)
        return _new_schedule(employee, data, actor)


def _delete_change(model, record_id: int, permission: str, actor) -> None:
    """Remove a change entered by mistake, unless an approved payroll used it."""
    with transaction.atomic():
        record = model.objects.select_related("employee").filter(pk=record_id).first()
        if record is None or (actor is not None and record.employee_id not in set(
                visible_employees(actor, permission).values_list("pk", flat=True))):
            raise NotFound(_("Not found."))
        if actor is not None:
            actor.require(permission, branch=record.employee.branch_id)
        locks.ensure_open(record.employee_id, record.effective_from, date.max)
        siblings = model.objects.filter(employee_id=record.employee_id)
        if siblings.order_by("effective_from", "id").first().pk == record.pk:
            raise DomainError(_("The first record can't be removed: it is what the employee "
                                "started with. Change the values from a later date instead."),
                              code="EMPLOYEES_FIRST_RECORD")
        record.delete()


def delete_pay_change(record_id: int, *, actor=None) -> None:
    _delete_change(Compensation, record_id, SALARY_MANAGE, actor)


def delete_schedule_change(record_id: int, *, actor=None) -> None:
    _delete_change(WorkSchedule, record_id, MANAGE, actor)


def end_employment(employee_id: int, left_on: date, reason: str = "", *,
                   actor=None) -> Employee:
    with transaction.atomic():
        employee = get_employee(employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        if left_on < employee.hired_on:
            raise invalid_fields({"left_on": [_("Must not be before the hiring date.")]})
        locks.ensure_open(employee.pk, left_on + timedelta(days=1), date.max)
        later = (employee.pay_history.filter(effective_from__gt=left_on).exists()
                 or employee.schedules.filter(effective_from__gt=left_on).exists())
        if later:
            raise invalid_fields({"left_on": [_("Pay or hours change after this date; remove those "
                                          "changes first.")]})
        employee.left_on, employee.leave_reason = left_on, reason.strip()
        employee.updated_by = getattr(actor, "user", None)
        employee.save(update_fields=["left_on", "leave_reason", "updated_by", "updated_at"])
        if left_on < timezone.localdate():
            _close_login(employee)
    return employee


def _close_login(employee: Employee) -> None:
    """Whoever has left signs in no more. The client's last Owner is kept, or nobody could get
    in to put it right."""
    if employee.member_id is None:
        return
    try:
        with transaction.atomic():
            iam.set_member_status(employee.member_id, MembershipStatus.SUSPENDED)
    except ValidationError as error:
        if error.code != "IAM_LAST_OWNER":
            raise
        logger.warning("Employee %s left but is the last owner: login kept", employee.pk)


def close_leavers_logins() -> int:
    """The logins of everyone whose last day has passed (a departure may be entered ahead)."""
    leavers = Employee.objects.filter(left_on__lt=timezone.localdate(),
                                      member__status=MembershipStatus.ACTIVE)
    for employee in leavers:
        _close_login(employee)
    return len(leavers)


def reinstate(employee_id: int, *, restore_login: bool = False, actor=None) -> Employee:
    """Undo a departure entered by mistake. The login opens again only when asked, by someone
    who may do that."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        employee.left_on, employee.leave_reason = None, ""
        employee.updated_by = getattr(actor, "user", None)
        employee.save(update_fields=["left_on", "leave_reason", "updated_by", "updated_at"])
        if restore_login:
            _open_login(employee, actor)
    return employee


def _open_login(employee: Employee, actor) -> None:
    if employee.member_id is not None and employee.member.status != MembershipStatus.ACTIVE:
        iam.set_member_status(employee.member_id, MembershipStatus.ACTIVE, actor=actor)
