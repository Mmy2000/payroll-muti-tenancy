"""URLs served on platform hosts (PLATFORM_HOSTS). No tenant context exists here: platform
code reads a client's data only inside that client's tenant_context.

Until the platform console (phase 8), platform staff work in the Django admin: clients, plans
and features (apps/platform/tenants/admin.py). New clients: `manage.py create_tenant`."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core import media


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", healthz),
    path("i18n/", include("django.conf.urls.i18n")),
    path("media/<path:path>", media.serve, name="media"),
    path("", RedirectView.as_view(url="/django-admin/", permanent=False), name="home"),
    path("django-admin/", admin.site.urls),
]
