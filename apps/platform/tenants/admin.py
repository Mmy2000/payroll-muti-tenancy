"""The raw Django admin for clients, plans and features, on platform hosts, for emergencies:
platform staff work in the console (apps/platform/console). A client's users never reach it."""

from django import forms
from django.contrib import admin
from django.utils.html import format_html_join
from django.utils.translation import gettext_lazy as _

from . import features
from .models import Plan, PlanFeature, PlatformEvent, Tenant, TenantDomain, TenantFeature


def _feature_choices():
    return [(f.key, f"{f.group} · {f.label}") for f in features.FEATURES]


class FeatureRowForm(forms.ModelForm):
    """A feature key picked from the registry, so a typo can't switch nothing."""

    key = forms.ChoiceField(label=_("Feature"), choices=_feature_choices)


class TenantDomainInline(admin.TabularInline):
    model = TenantDomain
    extra = 0


class TenantFeatureInline(admin.TabularInline):
    model = TenantFeature
    form = FeatureRowForm
    extra = 0
    verbose_name = _("feature set for this client (over its plan)")
    verbose_name_plural = _("features set for this client (over its plan)")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "status", "plan", "created_at")
    list_filter = ("status", "plan")
    search_fields = ("slug", "name")
    readonly_fields = ("effective_features",)
    inlines = [TenantDomainInline, TenantFeatureInline]

    def has_add_permission(self, request):
        return False  # a client is provisioned (manage.py create_tenant), never added bare

    def has_delete_permission(self, request, obj=None):
        return False  # tenants are archived then purged through tooling, never deleted here

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        features.forget(form.instance.pk)
        PlatformEvent.objects.create(actor=request.user, tenant=form.instance,
                                     action="feature.client")

    @admin.display(description=_("Features in effect"))
    def effective_features(self, tenant):
        if tenant.pk is None:
            return "-"
        rows = []
        for state in features.states(tenant):
            if state.enabled:
                status = _("on")
            elif state.blocked_by:
                status = _("off: needs %(names)s") % {
                    "names": ", ".join(str(f.label) for f in state.blocked_by)}
            else:
                status = _("off")
            source = _("client") if state.custom else _("plan")
            rows.append((state.feature.label, status, source))
        if not rows:
            return _("No features registered yet.")
        return format_html_join("", "<div>{}: <b>{}</b> ({})</div>", rows)


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    form = FeatureRowForm
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "price", "billing_period", "is_active", "is_default")
    inlines = [PlanFeatureInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        features.forget()  # every client on the plan
        PlatformEvent.objects.create(actor=request.user, action="feature.plan",
                                     detail={"plan": form.instance.code})


@admin.register(PlatformEvent)
class PlatformEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "tenant", "actor")
    list_filter = ("action",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
