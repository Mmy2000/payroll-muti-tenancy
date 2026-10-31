"""Console → Clients: the list, one client, its status, domains and access."""

from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.errors import ValidationError
from apps.platform.tenants import features as feature_registry
from apps.platform.tenants.models import Tenant, TenantStatus

from ..selectors import metrics
from ..selectors.events import client_events
from ..selectors.tenants import (
    LIVE_STATUSES,
    client_domains,
    client_owners,
    client_profile,
    find_domain,
    primary_domain,
    search_clients,
)
from ..services.clients import (
    LIMIT_FIELDS,
    add_domain,
    attr,
    create_client,
    remove_domain,
    set_client_status,
    update_client,
    update_client_profile,
)
from ..services.provisioning import ProvisionTenantCommand
from .common import back, get_tenant, show_form_errors, staff_required
from .forms import DomainForm, ProfileForm, TenantCreateForm, TenantSettingsForm, domain_for

# The traffic pages' enable/disable switch moves a client between these two only.
ACCESS_STATUSES = (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


# Which statuses can be set from the console (the key), and from which. Suspending stops every
# sign-in, app request and device call at once (TenantResolutionMiddleware); the data is kept.
TRANSITIONS = {
    TenantStatus.ACTIVE: (TenantStatus.SUSPENDED, TenantStatus.ARCHIVED,
                          TenantStatus.PROVISIONING),
    TenantStatus.SUSPENDED: (TenantStatus.ACTIVE,),
    TenantStatus.ARCHIVED: (TenantStatus.SUSPENDED,),
}


@staff_required
def tenants(request):
    term = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    queryset = search_clients(term, status, request.GET.get("plan", ""))
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    rows = [{"tenant": t, "domain": primary_domain(t),
             "usage": metrics.tenant_usage(t) if t.status in LIVE_STATUSES else None}
            for t in page.object_list]
    return render(request, "console/tenants.html", {
        "page": page, "rows": rows, "term": term, "status": status,
        "statuses": TenantStatus.choices, "section": "tenants"})


@staff_required
def tenant_new(request):
    """Sign a client up: its workspace, address, owner, plan and limits, in one step."""
    form = TenantCreateForm(request.POST or None,
                            initial={"plan": Tenant._meta.get_field("plan").get_default()})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            tenant = create_client(ProvisionTenantCommand(
                slug=d["slug"], name=d["name"], domain=domain_for(d["slug"]),
                owner_username=d["owner_username"],
                owner_password=d["owner_password"] or None, owner_email=d["owner_email"],
                owner_display_name=d["owner_display_name"],
                link_existing_owner=d["link_existing_owner"],
                functional_currency=d["functional_currency"], timezone=d["timezone"],
                locale=d["locale"], country=d["country"]), limits=d, actor=request.user)
        except ValidationError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, _("%(name)s is ready.") % {"name": tenant.name})
            return redirect("console-tenant", tenant.pk)
    return render(request, "console/tenant_new.html", {
        "form": form, "base_domain": domain_for(""), "section": "new"})


@staff_required
def tenant(request, pk):
    tenant = get_tenant(pk)
    usage = metrics.tenant_usage(tenant) if tenant.status in LIVE_STATUSES else None
    profile = client_profile(tenant)
    settings_form = TenantSettingsForm(initial={
        "name": tenant.name, **{name: getattr(tenant, attr(name)) for name in LIMIT_FIELDS}})
    profile_form = ProfileForm(initial={
        "display_name": profile.display_name, "locale": profile.locale,
        "country": profile.country, "timezone": profile.timezone,
        "accent": profile.accent, "logo": profile.logo or None} if profile else None)
    return render(request, "console/tenant.html", {
        "tenant": tenant, "usage": usage, "profile": profile,
        "domains": client_domains(tenant),
        "primary": primary_domain(tenant),
        "owners": client_owners(tenant) if profile else [],
        "profile_logo_url": profile.logo.url if profile and profile.logo else "",
        "events": client_events(tenant),
        "feature_states": feature_registry.states(tenant),
        "settings_form": settings_form, "profile_form": profile_form, "domain_form": DomainForm(),
        "transitions": [(s, TenantStatus(s).label) for s in TRANSITIONS
                        if tenant.status in TRANSITIONS[s]],
        "section": "tenants",
    })


@staff_required
@require_POST
def tenant_settings(request, pk):
    tenant = get_tenant(pk)
    form = TenantSettingsForm(request.POST, initial={"plan": tenant.plan_id})
    if not form.is_valid():
        show_form_errors(request, form)
        return redirect("console-tenant", pk)
    update_client(tenant, data=form.cleaned_data, actor=request.user)
    messages.success(request, _("Saved."))
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def tenant_profile(request, pk):
    tenant = get_tenant(pk)
    form = ProfileForm(request.POST, request.FILES)
    if not form.is_valid():
        show_form_errors(request, form)
        return redirect("console-tenant", pk)
    if update_client_profile(tenant, data=form.cleaned_data, actor=request.user) is None:
        raise Http404
    messages.success(request, _("Saved."))
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def tenant_status(request, pk):
    tenant = get_tenant(pk)
    status = request.POST.get("status", "")
    if status not in TRANSITIONS or tenant.status not in TRANSITIONS[status]:
        messages.error(request, _("That change is not allowed."))
        return redirect("console-tenant", pk)
    set_client_status(tenant, status=status, actor=request.user)
    messages.success(request, _("%(name)s is now %(status)s.")
                     % {"name": tenant.name, "status": tenant.get_status_display()})
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def domain_add(request, pk):
    tenant = get_tenant(pk)
    form = DomainForm(request.POST)
    if not form.is_valid():
        show_form_errors(request, form)
        return redirect("console-tenant", pk)
    add_domain(tenant, domain=form.cleaned_data["domain"], actor=request.user)
    messages.success(request, _("Domain added."))
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def domain_remove(request, pk, domain_id):
    tenant = get_tenant(pk)
    domain = find_domain(tenant, domain_id)
    if domain is None:
        raise Http404
    if domain.is_primary:
        messages.error(request, _("The main address cannot be removed."))
        return redirect("console-tenant", pk)
    remove_domain(tenant, domain=domain, actor=request.user)
    messages.success(request, _("Domain removed."))
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def tenant_access(request, pk):
    """Enable (active) or disable (suspended) a client. Disabling stops every sign-in and
    request at once; the data is kept. JSON for the live pages, a redirect otherwise."""
    tenant = get_tenant(pk)
    wants_json = "application/json" in request.headers.get("Accept", "")
    target = TenantStatus.ACTIVE if request.POST.get("enabled") == "1" else TenantStatus.SUSPENDED
    if tenant.status not in ACCESS_STATUSES:
        message = _("That change is not allowed.")
        if wants_json:
            return JsonResponse({"error": {"message": message}}, status=409)
        messages.error(request, message)
    else:
        set_client_status(tenant, status=target, actor=request.user)
        message = (_("%(name)s is enabled.") if target == TenantStatus.ACTIVE
                   else _("%(name)s is disabled.")) % {"name": tenant.name}
        if wants_json:
            return JsonResponse({"status": tenant.status, "message": message})
        messages.success(request, message)
    return back(request, reverse("console-tenant-traffic", args=[pk]))
