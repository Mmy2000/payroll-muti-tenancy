"""What every console page shares."""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.platform.tenants.models import Tenant

from ..selectors.tenants import find_client


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not request.user.is_platform_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def show_form_errors(request, form) -> None:
    for _field, errors in form.errors.items():
        for error in errors:
            messages.error(request, error)


def back(request, fallback: str, anchor: str = ""):
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = fallback
    return redirect(f"{next_url}{anchor}")


def get_tenant(pk: int) -> Tenant:
    tenant = find_client(pk)
    if tenant is None:
        raise Http404
    return tenant
