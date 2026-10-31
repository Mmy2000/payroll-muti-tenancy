"""The platform console: served on PLATFORM_HOSTS only, for platform staff. Clients (sign-up,
plan and limits, company settings, domains, status), plans, features, traffic, jobs, the
platform's branding and what staff did (PlatformEvent)."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.platform.tenants.models import (
    PlatformEvent,
    PlatformLink,
    PlatformSettings,
    TenantStatus,
)

from ..selectors import metrics
from .common import record, staff_required
from .forms import (
    PlatformLinkFormSet,
    PlatformSettingsForm,
    StaffLoginForm,
)
from .tenants import LIVE_STATUSES


class LoginView(auth_views.LoginView):
    template_name = "console/login.html"
    authentication_form = StaffLoginForm
    redirect_authenticated_user = True


# ---- Overview and clients ----


@staff_required
def home(request):
    data = metrics.overview()
    recent = PlatformEvent.objects.select_related("actor", "tenant")[:8]
    attention = sorted((u for u in data.tenants if u.health in ("idle", "new")
                        or u.tenant.status == TenantStatus.SUSPENDED),
                       key=lambda u: u.tenant.name)[:6]
    return render(request, "console/home.html", {
        "data": data, "recent": recent, "attention": attention, "section": "home"})


def tls_allowed(request):
    """Asked by the web server before it gets an HTTPS certificate for a domain on first visit
    (Caddy's on_demand_tls `ask`): 200 for the platform's own hosts and the domains of clients
    that are open or suspended (each client's `<slug>.<base>` address is one of its domains), 404
    for anything else: patterns like ".example.com" are not enough, or anyone could make the
    server ask for certificates for made-up subdomains."""
    from apps.platform.tenants.selectors import tenant_for_host

    domain = request.GET.get("domain", "").strip().lower().rstrip(".")
    tenant = tenant_for_host(domain) if domain else None
    known = (tenant.status in LIVE_STATUSES if tenant is not None
             else domain in {h.lower() for h in settings.PLATFORM_HOSTS})
    return HttpResponse(status=200 if known else 404)


@staff_required
def events(request):
    queryset = PlatformEvent.objects.select_related("actor", "tenant")
    tenant_id = request.GET.get("tenant", "")
    if tenant_id.isdigit():
        queryset = queryset.filter(tenant_id=int(tenant_id))
    page = Paginator(queryset, 50).get_page(request.GET.get("page"))
    return render(request, "console/events.html", {"page": page, "section": "events"})


# ---- Traffic ----
# The traffic pages are live: the browser re-fetches these parts every few seconds (…/live/)
# and swaps them in. Each part is rendered by the same template the full page includes.


# ---- Platform settings ----

@staff_required
def platform_settings(request):
    """The platform's name, logos and the links in every workspace's sidebar footer."""
    from django.core.files.storage import default_storage

    row = PlatformSettings.objects.filter(pk=1).first() or PlatformSettings(pk=1)
    before = {name: getattr(row, name).name for name in ("logo", "logo_dark")}
    form = PlatformSettingsForm(request.POST or None, request.FILES or None, instance=row)
    links = PlatformLinkFormSet(request.POST or None, prefix="links",
                                queryset=PlatformLink.objects.all())
    if request.method == "POST":
        if form.is_valid() and links.is_valid():
            form.save()
            links.save()
            PlatformSettings.objects.get(pk=1).save()  # drops the cached copy everywhere
            for name, old in before.items():
                if old and old != getattr(row, name).name:
                    default_storage.delete(old)
            logos = [name for name in form.changed_data if name.startswith("logo")]
            record(request, "platform.settings", None, **{
                name: form.cleaned_data[name] for name in form.changed_data
                if name not in logos}, **({"logos": ", ".join(logos)} if logos else {}))
            messages.success(request, _("Saved."))
            return redirect("console-settings")
        messages.error(request, _("Please correct the highlighted fields."))
    return render(request, "console/settings.html", {
        "form": form, "links": links, "settings_row": row, "section": "settings"})


# ---- Features (apps.platform.tenants.features) ----


# ---- Plans ----


