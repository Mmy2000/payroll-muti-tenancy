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
]
