"""Setting up pay policies: lateness and overtime policies with their bands, tax tables with
their brackets, insurance rates and public holidays.

Child rows (bands, brackets) are replaced as a whole on every save: they have no identity of
their own, and payroll copies what it used into the payslip, so nothing points at them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.errors import NotFound, ValidationError

from .domain.bands import Band, band_problems
from .domain.tax import Bracket, bracket_problems
from .models import (
    InsuranceRate,
    LatenessBand,
    LatenessPolicy,
    OvertimeBand,
    OvertimePolicy,
    PublicHoliday,
    TaxBracket,
    TaxTable,
)

BAND_MESSAGES = {
    "reversed": _lazy("'To' must not be less than 'from'."),
    "negative": _lazy("Hours must not be negative."),
    "overlap": _lazy("This band overlaps another one."),
}


def _invalid(fields: dict, message: str | None = None) -> ValidationError:
    return ValidationError(message or _("Please correct the highlighted fields."), fields=fields)


def _get(model, pk: int):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound(_("Not found."))
    return obj


# --- lateness and overtime policies --------------------------------------------------------


@dataclass(frozen=True)
class BandedPolicyInput:
    name: str
    minutes: int  # grace (lateness) or starts-after (overtime)
    bands: list[Band] = field(default_factory=list)


def _check_bands(bands: list[Band]) -> None:
    problems = band_problems(bands)
    if problems:
        raise _invalid({"bands": {str(i): [str(BAND_MESSAGES[p])] for i, p in problems.items()}})


def _save_banded(policy_model, band_model, hours_field: str, minutes_field: str, permission: str,
                 data: BandedPolicyInput, policy_id: int | None, actor):
    if actor is not None:
        actor.require(permission)
    name = data.name.strip()
    if not name:
        raise _invalid({"name": [_("Enter a name.")]})
    _check_bands(data.bands)
    with transaction.atomic():
        policy = policy_model() if policy_id is None else _get(policy_model, policy_id)
        if policy_model.objects.filter(name=name).exclude(pk=policy.pk).exists():
            raise _invalid({"name": [_("Another policy has this name.")]})
        policy.name = name
        setattr(policy, minutes_field, data.minutes)
        user = getattr(actor, "user", None)
        if policy.pk is None:
            policy.created_by = user
        policy.updated_by = user
        policy.save()
        band_model.objects.filter(policy=policy).delete()
        band_model.objects.bulk_create([
            band_model(policy=policy, from_minutes=b.from_minutes, to_minutes=b.to_minutes,
                       **{hours_field: b.hours})
            for b in sorted(data.bands, key=lambda b: b.from_minutes)])
    return policy


def save_lateness_policy(data: BandedPolicyInput, *, policy_id: int | None = None,
                         actor=None) -> LatenessPolicy:
    return _save_banded(LatenessPolicy, LatenessBand, "deduct_hours", "grace_minutes",
                        "policies.lateness.manage", data, policy_id, actor)


def save_overtime_policy(data: BandedPolicyInput, *, policy_id: int | None = None,
                         actor=None) -> OvertimePolicy:
    return _save_banded(OvertimePolicy, OvertimeBand, "paid_hours", "starts_after_minutes",
                        "policies.overtime.manage", data, policy_id, actor)


def set_policy_active(model, policy_id: int, active: bool, *, actor=None):
    permission = ("policies.lateness.manage" if model is LatenessPolicy
                  else "policies.overtime.manage")
    if actor is not None:
        actor.require(permission)
    policy = _get(model, policy_id)
    policy.is_active = active
    policy.save(update_fields=["is_active", "updated_at"])
    return policy


# --- income tax ----------------------------------------------------------------------------

BRACKET_MESSAGES = {
    "rate": _lazy("Enter a rate from 0 to 100."),
    "open_not_last": _lazy("Only the last bracket may have no upper limit."),
    "not_rising": _lazy("Each limit must be higher than the one before."),
}


@dataclass(frozen=True)
class TaxTableInput:
    effective_from: date
    annual_exemption: Decimal
    brackets: list[Bracket]
    note: str = ""


def save_tax_table(data: TaxTableInput, *, table_id: int | None = None,
                   actor=None) -> TaxTable:
    if actor is not None:
        actor.require("policies.tax.manage")
    if not data.brackets:
        raise _invalid({"brackets": [_("Add at least one bracket.")]})
    problems = bracket_problems(data.brackets)
    if problems:
        raise _invalid({"brackets": {str(i): [str(BRACKET_MESSAGES[p])]
                                     for i, p in problems.items()}})
    if data.annual_exemption < 0:
        raise _invalid({"annual_exemption": [_("Must not be negative.")]})
    with transaction.atomic():
        table = TaxTable() if table_id is None else _get(TaxTable, table_id)
        if TaxTable.objects.filter(effective_from=data.effective_from).exclude(
                pk=table.pk).exists():
            raise _invalid({"effective_from": [_("Another table starts on this date.")]})
        table.effective_from = data.effective_from
        table.annual_exemption = data.annual_exemption
        table.note = data.note.strip()
        table.updated_by = getattr(actor, "user", None)
        table.save()
        TaxBracket.objects.filter(table=table).delete()
        TaxBracket.objects.bulk_create([TaxBracket(table=table, up_to=b.up_to, rate=b.rate)
                                        for b in data.brackets])
    return table


def delete_tax_table(table_id: int, *, actor=None) -> None:
    # TODO(phase 4): refuse once a posted payroll used this table.
    if actor is not None:
        actor.require("policies.tax.manage")
    _get(TaxTable, table_id).delete()


# --- social insurance ----------------------------------------------------------------------


@dataclass(frozen=True)
class InsuranceRateInput:
    effective_from: date
    employee_rate: Decimal
    employer_rate: Decimal
    min_insured: Decimal | None = None
    max_insured: Decimal | None = None
    note: str = ""


def save_insurance_rate(data: InsuranceRateInput, *, rate_id: int | None = None,
                        actor=None) -> InsuranceRate:
    if actor is not None:
        actor.require("policies.insurance.manage")
    errors = {}
    for name in ("employee_rate", "employer_rate"):
        if not Decimal(0) <= getattr(data, name) <= Decimal(100):
            errors[name] = [_("Enter a rate from 0 to 100.")]
    if (data.min_insured is not None and data.max_insured is not None
            and data.max_insured < data.min_insured):
        errors["max_insured"] = [_("Must not be less than the minimum.")]
    if errors:
        raise _invalid(errors)
    with transaction.atomic():
        rate = InsuranceRate() if rate_id is None else _get(InsuranceRate, rate_id)
        if InsuranceRate.objects.filter(effective_from=data.effective_from).exclude(
                pk=rate.pk).exists():
            raise _invalid({"effective_from": [_("Other rates start on this date.")]})
        for name in ("effective_from", "employee_rate", "employer_rate", "min_insured",
                     "max_insured"):
            setattr(rate, name, getattr(data, name))
        rate.note = data.note.strip()
        rate.updated_by = getattr(actor, "user", None)
        rate.save()
    return rate


def delete_insurance_rate(rate_id: int, *, actor=None) -> None:
    # TODO(phase 4): refuse once a posted payroll used these rates.
    if actor is not None:
        actor.require("policies.insurance.manage")
    _get(InsuranceRate, rate_id).delete()


# --- public holidays -----------------------------------------------------------------------


@dataclass(frozen=True)
class HolidayInput:
    date: date
    name: str
    branch_id: int | None = None


def save_holiday(data: HolidayInput, *, holiday_id: int | None = None,
                 actor=None) -> PublicHoliday:
    if actor is not None:
        actor.require("policies.holiday.manage", branch=data.branch_id)
    name = data.name.strip()
    if not name:
        raise _invalid({"name": [_("Enter a name.")]})
    holiday = PublicHoliday() if holiday_id is None else _get(PublicHoliday, holiday_id)
    holiday.date, holiday.name, holiday.branch_id = data.date, name, data.branch_id
    holiday.updated_by = getattr(actor, "user", None)
    try:
        with transaction.atomic():
            holiday.save()
    except IntegrityError:
        raise _invalid({"date": [_("There is already a holiday on this day.")]}) from None
    return holiday


def delete_holiday(holiday_id: int, *, actor=None) -> None:
    holiday = _get(PublicHoliday, holiday_id)
    if actor is not None:
        actor.require("policies.holiday.manage", branch=holiday.branch_id)
    holiday.delete()
