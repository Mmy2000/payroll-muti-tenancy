"""What every console page shares."""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.platform.tenants.models import PlatformEvent, Tenant


def attr(name: str) -> str:
    """Form field → Tenant attribute (the plan is stored by its code)."""
    return "plan_id" if name == "plan" else name


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not request.user.is_platform_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def record(request, action: str, tenant: Tenant | None = None, **detail) -> None:
    PlatformEvent.objects.create(actor=request.user, tenant=tenant, action=action,
                                 detail={k: str(v) for k, v in detail.items()})


def show_form_errors(request, form) -> None:
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


def back(request, fallback: str, anchor: str = ""):
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = fallback
    return redirect(f"{next_url}{anchor}")


def get_tenant(pk: int) -> Tenant:
    tenant = Tenant.objects.select_related("plan").prefetch_related("domains").filter(
        pk=pk).first()
    if tenant is None:
        raise Http404
    return tenant
