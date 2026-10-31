"""The checks on an employee's card, pay and hours. Each returns its errors, by field."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

from apps.core import locks
from apps.core.crypto import blind_index
from apps.core.errors import invalid_fields
from apps.org.models import Branch, Department, Position, TenantProfile
from apps.policies.models import LatenessPolicy, OvertimePolicy

from .models import Employee, Gender, MaritalStatus, MilitaryStatus, PayFrequency, WageType, Weekday

if TYPE_CHECKING:
    from .services.employees import CompensationInput, EmployeeInput, ScheduleInput


NATIONAL_ID_PURPOSE = "employees.national_id"


def normalize_national_id(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def national_id_problem(value: str) -> str | None:
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


def check_placement(employee: Employee, branch_id: int, department_id: int | None,
                    position_id: int | None = None) -> dict:
    """Where the employee works. Someone already in a deactivated branch or department stays
    valid: only a move into one is refused."""
    errors: dict[str, list[str]] = {}
    if (branch_id != employee.branch_id
            and not Branch.objects.filter(pk=branch_id, is_active=True).exists()):
        errors["branch_id"] = [_("Choose an active branch.")]
    if department_id is not None:
        department = Department.objects.filter(pk=department_id).first()
        if department is None or (department_id != employee.department_id
                                  and not department.is_active):
            errors["department_id"] = [_("Choose an active department.")]
        elif department.branch_id != branch_id:
            errors["department_id"] = [_("This department isn't in the employee's branch.")]
    if (position_id is not None and position_id != employee.position_id
            and not Position.objects.filter(pk=position_id, is_active=True).exists()):
        errors["position_id"] = [_("Choose an active position.")]
    return errors


def check_card(data: EmployeeInput, employee: Employee) -> dict:
    errors: dict[str, list[str]] = {}
    if not data.name.strip():
        errors["name"] = [_("Enter a name.")]
    if data.code < 1:
        errors["code"] = [_("Enter a code from 1.")]
    elif Employee.objects.filter(code=data.code).exclude(pk=employee.pk).exists():
        errors["code"] = [_("Another employee has this code.")]
    errors.update(check_placement(employee, data.branch_id, data.department_id,
                                  data.position_id))
    for name, choices in (("gender", Gender), ("marital_status", MaritalStatus),
                          ("military_status", MilitaryStatus)):
        value = getattr(data, name)
        if value and value not in choices.values:
            errors[name] = [_("Choose from the list.")]
    national_id = normalize_national_id(data.national_id)
    problem = national_id_problem(national_id)
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


def check_pay(data: CompensationInput) -> dict:
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


def check_schedule(data: ScheduleInput) -> dict:
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


def check_change_date(employee: Employee, effective_from: date | None) -> date:
    if effective_from is None:
        raise invalid_fields({"effective_from": [_("Enter the date the change starts.")]})
    locks.ensure_open(employee.pk, effective_from, date.max)
    if effective_from < employee.hired_on:
        raise invalid_fields({"effective_from": [_("Must not be before the hiring date.")]})
    if employee.left_on is not None and effective_from > employee.left_on:
        raise invalid_fields({"effective_from": [_("Must not be after the day they left.")]})
    return effective_from
