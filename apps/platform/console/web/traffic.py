"""Console → Traffic: for the platform and for one client, live."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.platform.tenants.models import Tenant

from ..selectors import traffic as traffic_report
from ..services.clients import set_traffic_limit
from .common import get_tenant, show_form_errors, staff_required
from .forms import TrafficLimitForm

OVERVIEW_PARTS = {"tiles": "console/_traffic_tiles.html", "chart": "console/_traffic_chart.html",
                  "clients": "console/_traffic_rows.html"}


CLIENT_PARTS = {"tiles": "console/_traffic_tiles.html", "chart": "console/_traffic_chart.html",
                "routes": "console/_traffic_routes.html",
                "summary": "console/_traffic_summary.html", "access": "console/_access_card.html"}


def _live_strings() -> dict[str, str]:
    return {
        "updated": _("Live · updated %(time)s"), "paused": _("Paused"),
        "offline": _("Reconnecting…"), "pause": _("Pause"), "resume": _("Resume"),
        "disable_title": _("Disable %(name)s?"),
        "failed": _("Could not reach the server. Check your connection and try again."),
    }


def _traffic_context(request, tenant: Tenant | None = None) -> dict:
    report = traffic_report.report(request.GET.get("window", ""), tenant)
    context = {
        "report": report, "totals": report.totals, "windows": traffic_report.WINDOWS,
        "default_limit": settings.TENANT_REQUESTS_PER_MINUTE,
        "slow_ms": settings.TRAFFIC_SLOW_MS, "section": "traffic", "live_strings": _live_strings(),
    }
    if tenant is None:
        context["page_url"] = f"{reverse('console-traffic')}?window={report.key}"
    else:
        context.update({
            "tenant": tenant, "client": report.clients[0],
            "routes": traffic_report.routes(tenant, report.start),
            "page_url": f"{reverse('console-tenant-traffic', args=[tenant.pk])}"
                        f"?window={report.key}"})
    return context


def _live(request, parts: dict[str, str], context: dict) -> JsonResponse:
    return JsonResponse({
        "window": context["report"].key,
        "parts": {name: render_to_string(template, context, request=request)
                  for name, template in parts.items()},
    })


@staff_required
def traffic(request):
    return render(request, "console/traffic.html", _traffic_context(request))


@staff_required
def traffic_live(request):
    return _live(request, OVERVIEW_PARTS, _traffic_context(request))


@staff_required
def tenant_traffic(request, pk):
    tenant = get_tenant(pk)
    form = TrafficLimitForm(request.POST or None,
                            initial={"requests_per_minute": tenant.requests_per_minute})
    if request.method == "POST":
        if not form.is_valid():
            show_form_errors(request, form)
            return redirect("console-tenant-traffic", pk)
        set_traffic_limit(tenant, limit=form.cleaned_data["requests_per_minute"],
                          actor=request.user)
        messages.success(request, _("Saved."))
        window = traffic_report.window(request.GET.get("window", ""))
        return redirect(f"{request.path}?window={window}")
    return render(request, "console/tenant_traffic.html",
                  {**_traffic_context(request, tenant), "form": form})


@staff_required
def tenant_traffic_live(request, pk):
    return _live(request, CLIENT_PARTS, _traffic_context(request, get_tenant(pk)))
