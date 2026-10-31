"""Console → Features: what each plan and client has, with what each feature depends on."""

from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.platform.tenants import features as feature_registry
from apps.platform.tenants.models import Plan, Tenant

from .common import back, get_tenant, record, staff_required
from .tenants import LIVE_STATUSES


def _along_with(others) -> dict:
    return {"also": ", ".join(f.key for f in others)} if others else {}


def _say_along_with(request, others, on: bool) -> None:
    if others:
        messages.info(request, (_("Also switched on, because it is needed: %(names)s.") if on else
                                _("Also switched off, because they rely on it: %(names)s."))
                      % {"names": feature_registry.labels(others)})


@staff_required
def features(request):
    """Every feature, which plans include it by default, and how many clients have it on."""
    defaults = feature_registry.plan_defaults()
    live = list(Tenant.objects.filter(status__in=LIVE_STATUSES))
    usage = {f.key: 0 for f in feature_registry.FEATURES}
    for tenant in live:
        for key in feature_registry.enabled_keys(tenant.pk):
            if key in usage:
                usage[key] += 1
    plans = [(p.code, p.label) for p in Plan.objects.all()]
    in_effect = {code: feature_registry.effective(defaults.get(code, {})) for code, _l in plans}
    groups: dict[str, list] = {}
    for feature in feature_registry.FEATURES:
        groups.setdefault(str(feature.group), []).append({
            "feature": feature, "used_by": usage[feature.key],
            "requires": feature_registry.needs(feature.key),
            "plans": [(value, label, in_effect[value].get(feature.key, False),
                       feature_registry.labels(feature_registry.knock_on(
                           defaults.get(value, {}), feature.key, False)))
                      for value, label in plans]})
    return render(request, "console/features.html", {
        "groups": groups, "plans": plans, "clients": len(live), "section": "features"})


@staff_required
@require_POST
def plan_feature(request):
    key, plan = request.POST.get("key", ""), request.POST.get("plan", "")
    plan_row = Plan.objects.filter(code=plan).first()
    if key not in feature_registry.BY_KEY or plan_row is None:
        raise Http404
    enabled = request.POST.get("enabled") == "1"
    with transaction.atomic():
        others = feature_registry.set_for_plan(plan_row, key, enabled)
    record(request, "feature.plan", None, plan=plan, feature=key, enabled=enabled,
           **_along_with(others))
    feature = feature_registry.BY_KEY[key]
    messages.success(request, (_("%(feature)s is now included in %(plan)s.") if enabled else
                               _("%(feature)s is no longer included in %(plan)s."))
                     % {"feature": feature.label, "plan": plan_row.label})
    _say_along_with(request, others, enabled)
    return back(request, reverse("console-features"), f"#f-{key}")


@staff_required
@require_POST
def tenant_feature(request, pk):
    tenant = get_tenant(pk)
    key, state = request.POST.get("key", ""), request.POST.get("state", "")
    if key not in feature_registry.BY_KEY or state not in ("on", "off", "default"):
        raise Http404
    with transaction.atomic():
        others = feature_registry.set_for_client(tenant, key,
                                                 None if state == "default" else state == "on")
    record(request, "feature.client", tenant, feature=key, state=state, **_along_with(others))
    feature = feature_registry.BY_KEY[key]
    messages.success(request, {
        "on": _("%(feature)s is on for %(name)s."),
        "off": _("%(feature)s is off for %(name)s."),
        "default": _("%(feature)s follows the plan again for %(name)s."),
    }[state] % {"feature": feature.label, "name": tenant.name})
    _say_along_with(request, others, feature_registry.is_enabled(tenant.pk, key))
    return back(request, reverse("console-tenant", args=[pk]), f"#f-{key}")
