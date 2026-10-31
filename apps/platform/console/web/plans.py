"""Console → Plans."""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.platform.tenants import features as feature_registry
from apps.platform.tenants.models import Plan

from ..selectors.plans import clients_on, find_plan, plans_with_clients, replacement_for
from ..services.plans import delete_plan, save_plan
from .common import staff_required
from .forms import PlanDeleteForm, PlanForm


@staff_required
def plans(request):
    rows = plans_with_clients()
    defaults = feature_registry.plan_defaults()
    total = len(feature_registry.FEATURES)
    return render(request, "console/plans.html", {
        "plans": [{"plan": p,
                   "features_on": sum(on for _key, on in feature_registry.effective(
                       defaults.get(p.code, {})).items()),
                   "features_total": total} for p in rows],
        "section": "plans"})


def _plan_form(request, plan: Plan | None):
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        changed = [name for name in form.changed_data if not name.startswith("feature_")]
        save_plan(form.instance, features=form.feature_choices(), created=plan is None,
                  changes={name: form.cleaned_data[name] for name in changed if name != "code"},
                  actor=request.user)
        messages.success(request, _("Saved."))
        return redirect("console-plans")
    return render(request, "console/plan_form.html", {
        "form": form, "plan": plan, "section": "plans"})


@staff_required
def plan_new(request):
    return _plan_form(request, None)


@staff_required
def plan_edit(request, pk):
    plan = find_plan(pk)
    if plan is None:
        raise Http404
    return _plan_form(request, plan)


@staff_required
def plan_delete(request, pk):
    """Delete a plan. Its clients (if any) move to another plan first, in the same step."""
    plan = find_plan(pk)
    if plan is None:
        raise Http404
    clients = clients_on(plan)
    replacement = replacement_for(plan)
    if replacement is None:
        messages.error(request, _("The last plan cannot be deleted."))
        return redirect("console-plans")
    form = PlanDeleteForm(request.POST or None, plan=plan, initial={"move_to": replacement.code})
    if request.method == "POST" and form.is_valid():
        delete_plan(plan, clients=clients, move_to=form.cleaned_data["move_to"],
                    actor=request.user)
        messages.success(request, _("Plan deleted."))
        return redirect("console-plans")
    return render(request, "console/plan_delete.html", {
        "plan": plan, "clients": clients, "form": form, "section": "plans"})
