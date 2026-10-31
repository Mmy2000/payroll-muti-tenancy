"""Console → Clients: the list, one client, its status, domains and access."""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.errors import ValidationError
from apps.core.media import replace_file
from apps.core.tenancy import tenant_context
from apps.platform.tenants import features as feature_registry
from apps.platform.tenants.models import Plan, Tenant, TenantDomain, TenantStatus
from apps.platform.tenants.services import ProvisionTenantCommand, provision_tenant

from ..selectors import metrics
from .common import attr, back, get_tenant, record, show_form_errors, staff_required
from .forms import DomainForm, ProfileForm, TenantCreateForm, TenantSettingsForm, domain_for

LIMIT_FIELDS = ("plan", "trial_ends_on", "max_branches", "max_users", "max_app_logins",
                "contact_name", "contact_email", "contact_phone", "notes")


# The traffic pages' enable/disable switch moves a client between these two only.
ACCESS_STATUSES = (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


LIVE_STATUSES = (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


# Which statuses can be set from the console (the key), and from which. Suspending stops every
# sign-in, app request and device call at once (TenantResolutionMiddleware); the data is kept.
TRANSITIONS = {
    TenantStatus.ACTIVE: (TenantStatus.SUSPENDED, TenantStatus.ARCHIVED,
                          TenantStatus.PROVISIONING),
    TenantStatus.SUSPENDED: (TenantStatus.ACTIVE,),
    TenantStatus.ARCHIVED: (TenantStatus.SUSPENDED,),
}


def _primary_domain(tenant: Tenant) -> str | None:
    domain = next((d for d in tenant.domains.all() if d.is_primary), None)
    return domain.domain if domain else None


@staff_required
def tenants(request):
    term = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    queryset = Tenant.objects.select_related("plan").prefetch_related("domains").order_by("name")
    if term:
        queryset = queryset.filter(Q(name__icontains=term) | Q(slug__icontains=term)
                                   | Q(contact_name__icontains=term)
                                   | Q(contact_email__icontains=term)
                                   | Q(domains__domain__icontains=term)).distinct()
    if status in TenantStatus.values:
        queryset = queryset.filter(status=status)
    plan_code = request.GET.get("plan", "")
    if plan_code:
        queryset = queryset.filter(plan_id=plan_code)
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    rows = [{"tenant": t, "domain": _primary_domain(t),
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
            with transaction.atomic():
                tenant = provision_tenant(ProvisionTenantCommand(
                    slug=d["slug"], name=d["name"], domain=domain_for(d["slug"]),
                    owner_username=d["owner_username"],
                    owner_password=d["owner_password"] or None, owner_email=d["owner_email"],
                    owner_display_name=d["owner_display_name"],
                    link_existing_owner=d["link_existing_owner"],
                    functional_currency=d["functional_currency"], timezone=d["timezone"],
                    locale=d["locale"], country=d["country"]))
                for name in LIMIT_FIELDS:
                    setattr(tenant, attr(name), d[name] if d[name] is not None else
                            Tenant._meta.get_field(name).get_default())
                plan = Plan.objects.get(code=tenant.plan_id)
                if tenant.trial_ends_on is None and plan.trial_days:
                    tenant.trial_ends_on = timezone.localdate() + timedelta(days=plan.trial_days)
                tenant.save()
        except ValidationError as exc:
            form.add_error(None, exc.message)
        else:
            record(request, "tenant.created", tenant, slug=tenant.slug, plan=tenant.plan_id)
            messages.success(request, _("%(name)s is ready.") % {"name": tenant.name})
            return redirect("console-tenant", tenant.pk)
    return render(request, "console/tenant_new.html", {
        "form": form, "base_domain": domain_for(""), "section": "new"})


def _owners(tenant: Tenant) -> list:
    from apps.iam.catalog import OWNER
    from apps.iam.models import Membership

    with tenant_context(tenant.id):
        return list(Membership.objects.select_related("user").filter(
            roles__role__code=OWNER).order_by("username"))


@staff_required
def tenant(request, pk):
    from apps.org.models import TenantProfile

    tenant = get_tenant(pk)
    usage = metrics.tenant_usage(tenant) if tenant.status in LIVE_STATUSES else None
    profile = None
    if tenant.status != TenantStatus.PURGED:
        with tenant_context(tenant.id):
            profile = TenantProfile.objects.first()
    settings_form = TenantSettingsForm(initial={
        "name": tenant.name, **{name: getattr(tenant, attr(name)) for name in LIMIT_FIELDS}})
    profile_form = ProfileForm(initial={
        "display_name": profile.display_name, "locale": profile.locale,
        "country": profile.country, "timezone": profile.timezone,
        "accent": profile.accent, "logo": profile.logo or None} if profile else None)
    return render(request, "console/tenant.html", {
        "tenant": tenant, "usage": usage, "profile": profile,
        "domains": tenant.domains.order_by("-is_primary", "domain"),
        "primary": _primary_domain(tenant),
        "owners": _owners(tenant) if profile else [],
        "profile_logo_url": profile.logo.url if profile and profile.logo else "",
        "events": tenant.events.select_related("actor")[:12],
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
    before = {name: getattr(tenant, attr(name)) for name in ("name", *LIMIT_FIELDS)}
    tenant.name = form.cleaned_data["name"]
    for name in LIMIT_FIELDS:
        setattr(tenant, attr(name), form.cleaned_data[name])
    tenant.save()
    changed = {name: getattr(tenant, attr(name)) for name in before
               if getattr(tenant, attr(name)) != before[name]}
    record(request, "tenant.updated", tenant, **changed)
    messages.success(request, _("Saved."))
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def tenant_profile(request, pk):
    from apps.org.models import TenantProfile

    tenant = get_tenant(pk)
    form = ProfileForm(request.POST, request.FILES)
    if not form.is_valid():
        show_form_errors(request, form)
        return redirect("console-tenant", pk)
    data = dict(form.cleaned_data)
    logo = data.pop("logo")
    with tenant_context(tenant.id):
        profile = TenantProfile.objects.first()
        if profile is None:
            raise Http404
        for name, value in data.items():
            setattr(profile, name, value)
        replace_file(profile, "logo", logo)
        profile.save()
    if logo is not None:
        data["logo"] = _("removed") if logo is False else logo.name
    record(request, "profile.updated", tenant, **data)
    messages.success(request, _("Saved."))
    return redirect("console-tenant", pk)


def _set_status(request, tenant: Tenant, status: str) -> None:
    if tenant.status == status:
        return
    previous = tenant.status
    tenant.status = status
    tenant.save(update_fields=["status", "updated_at"])
    record(request, "tenant.status", tenant, before=previous, after=status)


@staff_required
@require_POST
def tenant_status(request, pk):
    tenant = get_tenant(pk)
    status = request.POST.get("status", "")
    if status not in TRANSITIONS or tenant.status not in TRANSITIONS[status]:
        messages.error(request, _("That change is not allowed."))
        return redirect("console-tenant", pk)
    _set_status(request, tenant, status)
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
    domain = form.cleaned_data["domain"]
    TenantDomain.objects.create(tenant=tenant, domain=domain)
    record(request, "domain.added", tenant, domain=domain)
    messages.success(request, _("Domain added."))
    return redirect("console-tenant", pk)


@staff_required
@require_POST
def domain_remove(request, pk, domain_id):
    tenant = get_tenant(pk)
    domain = tenant.domains.filter(pk=domain_id).first()
    if domain is None:
        raise Http404
    if domain.is_primary:
        messages.error(request, _("The main address cannot be removed."))
        return redirect("console-tenant", pk)
    record(request, "domain.removed", tenant, domain=domain.domain)
    domain.delete()
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
        _set_status(request, tenant, target)
        message = (_("%(name)s is enabled.") if target == TenantStatus.ACTIVE
                   else _("%(name)s is disabled.")) % {"name": tenant.name}
        if wants_json:
            return JsonResponse({"status": tenant.status, "message": message})
        messages.success(request, message)
    return back(request, reverse("console-tenant-traffic", args=[pk]))
