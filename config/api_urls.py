from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from apps.core.api.permissions import HasTenantPermission
from apps.iam.catalog import AUTHENTICATED


class SchemaView(SpectacularAPIView):
    # drf-spectacular sets its own permission_classes (AllowAny by default), which would
    # skip the project's default and publish the schema to anyone: keep ours.
    permission_classes = [HasTenantPermission]
    required_permissions = {"GET": AUTHENTICATED}


urlpatterns = [
    path("schema/", SchemaView.as_view(), name="api-schema"),
    path("iam/", include("apps.iam.api.urls")),
    path("org/", include("apps.org.api.urls")),
    path("employees/", include("apps.employees.api.views")),
    path("policies/", include("apps.policies.api.views")),
    path("compensation/", include("apps.compensation.api.views")),
    path("attendance/", include("apps.attendance.api.views")),
    path("loans/", include("apps.loans.api.views")),
    path("adjustments/", include("apps.adjustments.api.views")),
    path("payroll/", include("apps.payroll.api.views")),
    path("devices/", include("apps.devices.api.views")),
    path("mobile/", include("apps.mobile.web_api")),
    path("messaging/", include("apps.messaging.api")),
    path("notifications/", include("apps.notifications.api")),
    path("evaluations/", include("apps.evaluations.api")),
]
