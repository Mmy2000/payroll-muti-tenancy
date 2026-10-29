"""Employees: their card, their pay history and their working hours.

Permissions follow the employee's branch: a member allowed in some branches sees and manages only
the employees of those branches. Pay is a permission of its own (`employees.salary.read` /
`employees.salary.manage`), so a member can keep cards without seeing what anyone earns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.crypto import blind_index, encrypt
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.org.models import Branch, Department, TenantProfile
from apps.policies.models import LatenessPolicy, OvertimePolicy

from .models import (
    Compensation,
    Employee,
    Gender,
    MaritalStatus,
    MilitaryStatus,
    PayFrequency,
    WageType,
    Weekday,
    WorkSchedule,
)

VIEW, MANAGE = "employees.employee.view", "employees.employee.manage"
SALARY_READ, SALARY_MANAGE = "employees.salary.read", "employees.salary.manage"
NATIONAL_ID_PURPOSE = "employees.national_id"


def _invalid(fields: dict) -> ValidationError:
    return ValidationError(_("Please correct the highlighted fields."), fields=fields)


def visible_employees(actor, code: str = VIEW):
    """Employees of the branches where `actor` holds `code` (all of them for a trusted caller)."""
    employees = Employee.objects.all()
    if actor is None:
        return employees
    branches = actor.branch_ids(code)
    return employees if branches is None else employees.filter(branch_id__in=branches)


def get_employee(employee_id: int, actor=None, code: str = VIEW, *, lock=False) -> Employee:
    employees = visible_employees(actor, code)
    if lock:
        employees = employees.select_for_update(of=("self",))
    employee = employees.filter(pk=employee_id).first()
    if employee is None:
        raise NotFound(_("Not found."))
    return employee


def next_code() -> int:
    return (Employee.objects.aggregate(top=Max("code"))["top"] or 0) + 1


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


def normalize_national_id(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _national_id_problem(value: str) -> str | None:
    if not value:
        return None
    if not value.isdigit():
        return _("Use digits only.")
    profile = TenantProfile.objects.first()
    if profile is not None and profile.country == "EG" and len(value) != 14:
        return _("An Egyptian national ID has 14 digits.")
    if not 5 <= len(value) <= 20:
        return _("Enter a valid national ID.")
    return None


def _check_card(data: EmployeeInput, employee: Employee) -> dict:
    errors: dict[str, list[str]] = {}
    if not data.name.strip():
        errors["name"] = [_("Enter a name.")]
    if data.code < 1:
        errors["code"] = [_("Enter a code from 1.")]
    elif Employee.objects.filter(code=data.code).exclude(pk=employee.pk).exists():
        errors["code"] = [_("Another employee has this code.")]
    if not Branch.objects.filter(pk=data.branch_id, is_active=True).exists():
        errors["branch_id"] = [_("Choose an active branch.")]
    if data.department_id is not None and not Department.objects.filter(
            pk=data.department_id, is_active=True).exists():
        errors["department_id"] = [_("Choose an active department.")]
    for name, choices in (("gender", Gender), ("marital_status", MaritalStatus),
                          ("military_status", MilitaryStatus)):
        value = getattr(data, name)
        if value and value not in choices.values:
            errors[name] = [_("Choose from the list.")]
    national_id = normalize_national_id(data.national_id)
    problem = _national_id_problem(national_id)
    if problem:
        errors["national_id"] = [problem]
    elif national_id and Employee.objects.filter(
            national_id_index=blind_index(national_id, purpose=NATIONAL_ID_PURPOSE)).exclude(
            pk=employee.pk).exists():
        errors["national_id"] = [_("Another employee has this national ID.")]
    if employee.left_on is not None and data.hired_on > employee.left_on:
        errors["hired_on"] = [_("Must not be after the day they left.")]
    if data.birth_date is not None and data.birth_date >= data.hired_on:
        errors["birth_date"] = [_("Must be before the hiring date.")]
    return errors


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


def _check_pay(data: CompensationInput) -> dict:
    errors: dict[str, list[str]] = {}
    if data.wage_type not in WageType.values:
        errors["wage_type"] = [_("Choose how the pay is counted.")]
    if data.pay_frequency not in PayFrequency.values:
        errors["pay_frequency"] = [_("Choose how often the employee is paid.")]
    if data.salary < 0:
        errors["salary"] = [_("Must not be negative.")]
    if not Decimal(0) < data.hours_per_day <= Decimal(24):
        errors["hours_per_day"] = [_("Enter hours from more than 0 to 24.")]
    for name in ("overtime_multiplier", "absence_multiplier", "holiday_multiplier",
                 "permission_hours"):
        if getattr(data, name) < 0:
            errors[name] = [_("Must not be negative.")]
    if data.insured_salary is not None and data.insured_salary < 0:
        errors["insured_salary"] = [_("Must not be negative.")]
    return errors


def _check_schedule(data: ScheduleInput) -> dict:
    errors: dict[str, list[str]] = {}
    if data.starts_at == data.ends_at:
        errors["ends_at"] = [_("The shift must end at another time than it starts.")]
    days = set(data.days_off)
    if not days <= set(Weekday.values):
        errors["days_off"] = [_("Choose days of the week.")]
    elif len(days) == 7:
        errors["days_off"] = [_("At least one day must be a working day.")]
    if data.lateness_policy_id is not None and not LatenessPolicy.objects.filter(
            pk=data.lateness_policy_id, is_active=True).exists():
        errors["lateness_policy_id"] = [_("Choose an active policy.")]
    if data.overtime_policy_id is not None and not OvertimePolicy.objects.filter(
            pk=data.overtime_policy_id, is_active=True).exists():
        errors["overtime_policy_id"] = [_("Choose an active policy.")]
    return errors


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
        errors = {**_check_card(data, employee), **_prefixed("pay", _check_pay(pay)),
                  **_prefixed("schedule", _check_schedule(schedule))}
        if errors:
            raise _invalid(errors)
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
        errors = _check_card(data, employee)
        first_pay = employee.pay_history.order_by("effective_from").first()
        if first_pay is not None and data.hired_on > first_pay.effective_from:
            errors.setdefault("hired_on", [_("Pay is recorded from an earlier date.")])
        if errors:
            raise _invalid(errors)
        _apply_card(employee, data, actor)
        employee.save()
    return employee


def _check_change_date(employee: Employee, effective_from: date | None) -> date:
    if effective_from is None:
        raise _invalid({"effective_from": [_("Enter the date the change starts.")]})
    locks.ensure_open(employee.pk, effective_from, date.max)
    if effective_from < employee.hired_on:
        raise _invalid({"effective_from": [_("Must not be before the hiring date.")]})
    if employee.left_on is not None and effective_from > employee.left_on:
        raise _invalid({"effective_from": [_("Must not be after the day they left.")]})
    return effective_from


def change_pay(employee_id: int, data: CompensationInput, *, actor=None) -> Compensation:
    """New pay from a date. Earlier months keep the pay they had."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, SALARY_MANAGE, lock=True)
        if actor is not None:
            actor.require(SALARY_MANAGE, branch=employee.branch_id)
        start = _check_change_date(employee, data.effective_from)
        errors = _check_pay(data)
        if employee.pay_history.filter(effective_from=start).exists():
            errors["effective_from"] = [_("Pay already changes on this date.")]
        if errors:
            raise _invalid(errors)
        return _new_pay(employee, data, actor)


def change_schedule(employee_id: int, data: ScheduleInput, *, actor=None) -> WorkSchedule:
    """New working hours from a date. Earlier days keep the hours they had."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        start = _check_change_date(employee, data.effective_from)
        errors = _check_schedule(data)
        if employee.schedules.filter(effective_from=start).exists():
            errors["effective_from"] = [_("The hours already change on this date.")]
        if errors:
            raise _invalid(errors)
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
            raise _invalid({"left_on": [_("Must not be before the hiring date.")]})
        locks.ensure_open(employee.pk, left_on + timedelta(days=1), date.max)
        later = (employee.pay_history.filter(effective_from__gt=left_on).exists()
                 or employee.schedules.filter(effective_from__gt=left_on).exists())
        if later:
            raise _invalid({"left_on": [_("Pay or hours change after this date; remove those "
                                          "changes first.")]})
        employee.left_on, employee.leave_reason = left_on, reason.strip()
        employee.updated_by = getattr(actor, "user", None)
        employee.save(update_fields=["left_on", "leave_reason", "updated_by", "updated_at"])
    return employee


def reinstate(employee_id: int, *, actor=None) -> Employee:
    """Undo a departure entered by mistake."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)
        employee.left_on, employee.leave_reason = None, ""
        employee.updated_by = getattr(actor, "user", None)
        employee.save(update_fields=["left_on", "leave_reason", "updated_by", "updated_at"])
    return employee
