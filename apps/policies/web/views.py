"""Pages for the pay policies. They read and render; every save goes to the JSON API."""

from __future__ import annotations

from dataclasses import dataclass

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.iam.authz import permission_required
from apps.policies import selectors
from apps.policies.models import LatenessPolicy, OvertimePolicy


def _found(obj):
    if obj is None:
        raise Http404
    return obj


# --- lateness and overtime: one pair of templates, two sets of words -------------------------


@dataclass(frozen=True)
class BandedKind:
    model: type
    area: str  # permission area and URL name prefix
    title: object
    intro: object
    new_label: object
    minutes_label: object
    minutes_help: object
    minutes_field: str
    hours_label: object
    hours_field: str
    bands_help: object


LATENESS = BandedKind(
    LatenessPolicy, "lateness", _("Lateness policies"),
    _("How late arrivals are deducted: minutes late fall in a band that says how many hours of "
      "pay are lost."),
    _("New lateness policy"), _("Grace minutes"),
    _("Being this many minutes late or less is not deducted."), "grace_minutes",
    _("Hours deducted"), "deduct_hours",
    _("Minutes late from–to, and the hours of pay deducted. Without bands, the exact time "
      "missed is deducted."))
OVERTIME = BandedKind(
    OvertimePolicy, "overtime", _("Overtime policies"),
    _("How extra time is paid: minutes worked over fall in a band that says how many hours "
      "are paid, at the employee's overtime rate."),
    _("New overtime policy"), _("Overtime starts after (minutes)"),
    _("Staying this many minutes after the shift or less is not overtime."),
    "starts_after_minutes", _("Hours paid"), "paid_hours",
    _("Minutes over from–to, and the hours paid. Without bands, the time actually worked over "
      "is paid."))


def _banded_list(request, kind: BandedKind):
    policies = selectors.listed_banded_policies(kind.model)
    return render(request, "policies/banded_list.html", {"kind": kind, "policies": policies})


def _banded_form(request, kind: BandedKind, pk=None):
    policy = _found(selectors.find_banded_policy(kind.model, pk)) if pk else None
    bands = ([{"from": b.from_minutes, "to": b.to_minutes, "hours": getattr(b, kind.hours_field)}
              for b in policy.bands.all()] if policy else [])
    return render(request, "policies/banded_form.html", {
        "kind": kind, "policy": policy, "bands": bands,
        "minutes": getattr(policy, kind.minutes_field) if policy else 0,
        "endpoint": (reverse(f"{kind.area}-policy-detail", args=[policy.pk]) if policy
                     else reverse(f"{kind.area}-policy-list")),
        "method": "PUT" if policy else "POST",
        "list_url": reverse(f"{kind.area}-policies"),
    })


@permission_required("policies.lateness.view")
def lateness_policies(request):
    return _banded_list(request, LATENESS)


@permission_required("policies.lateness.manage")
def lateness_policy_new(request):
    return _banded_form(request, LATENESS)


@permission_required("policies.lateness.manage")
def lateness_policy_edit(request, pk):
    return _banded_form(request, LATENESS, pk)


@permission_required("policies.overtime.view")
def overtime_policies(request):
    return _banded_list(request, OVERTIME)


@permission_required("policies.overtime.manage")
def overtime_policy_new(request):
    return _banded_form(request, OVERTIME)


@permission_required("policies.overtime.manage")
def overtime_policy_edit(request, pk):
    return _banded_form(request, OVERTIME, pk)


# --- income tax ----------------------------------------------------------------------------


@permission_required("policies.tax.view")
def tax_tables(request):
    return render(request, "policies/tax_tables.html",
                  {"tables": selectors.listed_tax_tables()})


def _tax_form(request, pk=None):
    table = _found(selectors.find_tax_table(pk)) if pk else None
    return render(request, "policies/tax_table_form.html", {
        "table": table,
        "brackets": list(table.brackets.all()) if table else [],
        "endpoint": (reverse("tax-table-detail", args=[table.pk]) if table
                     else reverse("tax-table-list")),
        "method": "PUT" if table else "POST",
    })


@permission_required("policies.tax.manage")
def tax_table_new(request):
    return _tax_form(request)


@permission_required("policies.tax.manage")
def tax_table_edit(request, pk):
    return _tax_form(request, pk)


# --- social insurance ----------------------------------------------------------------------


@permission_required("policies.insurance.view")
def insurance_rates(request):
    return render(request, "policies/insurance_rates.html",
                  {"rates": selectors.listed_insurance_rates()})


def _insurance_form(request, pk=None):
    rate = _found(selectors.find_insurance_rate(pk)) if pk else None
    return render(request, "policies/insurance_rate_form.html", {
        "rate": rate,
        "endpoint": (reverse("insurance-rate-detail", args=[rate.pk]) if rate
                     else reverse("insurance-rate-list")),
        "method": "PUT" if rate else "POST",
    })


@permission_required("policies.insurance.manage")
def insurance_rate_new(request):
    return _insurance_form(request)


@permission_required("policies.insurance.manage")
def insurance_rate_edit(request, pk):
    return _insurance_form(request, pk)


# --- public holidays -----------------------------------------------------------------------


@permission_required("policies.holiday.view")
def holidays(request):
    allowed = request.actor.branch_ids("policies.holiday.manage")
    return render(request, "policies/holidays.html", {
        "holidays": selectors.listed_holidays(),
        "branches": selectors.branch_choices(allowed),
        "all_branches": allowed is None,
    })
