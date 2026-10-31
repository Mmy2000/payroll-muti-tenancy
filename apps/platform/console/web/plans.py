"""Console → Plans."""

from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.platform.tenants import features as feature_registry
from apps.platform.tenants.models import Plan, TenantStatus

from .common import record, staff_required
from .forms import PlanDeleteForm, PlanForm


@staff_required
def plans(request):
    rows = Plan.objects.annotate(
        clients=Count("tenants", distinct=True),
        live=Count("tenants", filter=Q(tenants__status=TenantStatus.ACTIVE), distinct=True))
    defaults = feature_registry.plan_defaults()
    total = len(feature_registry.FEATURES)
    return render(request, "console/plans.html", {
        "plans": [{"plan": p,
                   "features_on": sum(feature_registry.effective(
                       defaults.get(p.code, {})).values()),
                   "features_total": total} for p in rows],
        "section": "plans"})


def _plan_form(request, plan: Plan | None):
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        changed = [name for name in form.changed_data if not name.startswith("feature_")]
        with transaction.atomic():
            saved = form.save()
            form.save_features(saved)
        feature_registry.forget()
        record(request, "plan.updated" if plan else "plan.created", None, plan=saved.code,
               **{name: form.cleaned_data[name] for name in changed if name != "code"})
        messages.success(request, _("Saved."))
        return redirect("console-plans")
    return render(request, "console/plan_form.html", {
        "form": form, "plan": plan, "section": "plans"})


@staff_required
def plan_new(request):
    return _plan_form(request, None)


@staff_required
def plan_edit(request, pk):
    plan = Plan.objects.filter(pk=pk).first()
    if plan is None:
        raise Http404
    return _plan_form(request, plan)


@staff_required
def plan_delete(request, pk):
    """Delete a plan. Its clients (if any) move to another plan first, in the same step."""
    plan = Plan.objects.filter(pk=pk).first()
    if plan is None:
        raise Http404
    clients = list(plan.tenants.order_by("name"))
    others = Plan.objects.exclude(pk=plan.pk)
    if not others.exists():
        messages.error(request, _("The last plan cannot be deleted."))
        return redirect("console-plans")
    form = PlanDeleteForm(request.POST or None, plan=plan, initial={
        "move_to": (others.filter(is_default=True).first() or others.first()).code})
    if request.method == "POST" and form.is_valid():
        target = Plan.objects.get(code=form.cleaned_data["move_to"])
        with transaction.atomic():
            for tenant in clients:
                tenant.plan = target
                tenant.save(update_fields=["plan", "updated_at"])
                record(request, "tenant.updated", tenant, plan=target.code)
            if plan.is_default:
                target.is_default, target.is_active = True, True
                target.save()
            code = plan.code
            plan.delete()
        feature_registry.forget()
        record(request, "plan.deleted", None, plan=code, moved_to=target.code,
               clients=len(clients))
        messages.success(request, _("Plan deleted."))
        return redirect("console-plans")
    return render(request, "console/plan_delete.html", {
        "plan": plan, "clients": clients, "form": form, "section": "plans"})
