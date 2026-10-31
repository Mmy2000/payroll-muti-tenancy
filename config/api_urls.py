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
    path("employees/", include("apps.employees.api.urls")),
    path("policies/", include("apps.policies.api.urls")),
    path("compensation/", include("apps.compensation.api.urls")),
    path("attendance/", include("apps.attendance.api.urls")),
    path("loans/", include("apps.loans.api.urls")),
    path("adjustments/", include("apps.adjustments.api.urls")),
    path("payroll/", include("apps.payroll.api.urls")),
    path("devices/", include("apps.devices.api.urls")),
    path("mobile/", include("apps.mobile.api.web.urls")),
    path("messaging/", include("apps.messaging.api.urls")),
    path("notifications/", include("apps.notifications.api.urls")),
    path("evaluations/", include("apps.evaluations.api.urls")),
]
