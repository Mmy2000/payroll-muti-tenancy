"""URLs served on tenant hosts. The Django admin is deliberately absent (platform host only).

Each phase adds its screens here; their JSON endpoints go in config/api_urls.py."""

from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.attendance.web import views as attendance
from apps.audit import views as audit
from apps.compensation.web import views as compensation
from apps.core import media
from apps.employees.web import views as employees
from apps.iam.web import views as iam
from apps.iam.web.forms import WorkspaceLoginForm
from apps.org.web import company
from apps.org.web import views as org
from apps.policies.web import views as policies

urlpatterns = [
    path("", org.home, name="home"),
    path("login/", auth_views.LoginView.as_view(
        redirect_authenticated_user=True, authentication_form=WorkspaceLoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("media/<path:path>", media.serve, name="media"),

    path("settings/company/", company.company, name="company"),
    path("branches/", org.branches, name="branches"),
    path("branches/new/", org.branch_new, name="branch-new"),
    path("branches/<int:pk>/", org.branch_edit, name="branch-edit"),
    path("departments/", org.departments, name="departments"),
    path("departments/new/", org.department_new, name="department-new"),
    path("departments/<int:pk>/", org.department_edit, name="department-edit"),

    path("employees/", employees.employees, name="employees"),
    path("employees/new/", employees.employee_new, name="employee-new"),
    path("employees/import/", employees.employee_import, name="employee-import"),
    path("employees/import/template.xlsx", employees.employee_import_template,
         name="employee-import-template"),
    path("employees/<int:pk>/", employees.employee, name="employee"),
    path("employees/<int:pk>/edit/", employees.employee_edit, name="employee-edit"),

    path("attendance/", attendance.daily, name="attendance"),
    path("attendance/employees/<int:pk>/", attendance.employee_month,
         name="attendance-employee"),
    path("attendance/import/", attendance.punch_import, name="attendance-import"),
    path("attendance/import/template.xlsx", attendance.punch_import_template,
         name="attendance-import-template"),
    path("attendance/leave/", attendance.leave_requests, name="leave-requests"),
    path("attendance/leave/new/", attendance.leave_request_new, name="leave-request-new"),
    path("attendance/leave/types/", attendance.leave_types, name="leave-types"),
    path("attendance/hourly/", attendance.hourly_leave, name="hourly-leave"),
    path("attendance/hourly/new/", attendance.hourly_leave_new, name="hourly-leave-new"),

    path("pay-setup/items/", compensation.pay_items, name="pay-items"),
    path("pay-setup/items/new/", compensation.pay_item_new, name="pay-item-new"),
    path("pay-setup/items/<int:pk>/", compensation.pay_item_edit, name="pay-item-edit"),
    path("pay-setup/lateness/", policies.lateness_policies, name="lateness-policies"),
    path("pay-setup/lateness/new/", policies.lateness_policy_new, name="lateness-policy-new"),
    path("pay-setup/lateness/<int:pk>/", policies.lateness_policy_edit,
         name="lateness-policy-edit"),
    path("pay-setup/overtime/", policies.overtime_policies, name="overtime-policies"),
    path("pay-setup/overtime/new/", policies.overtime_policy_new, name="overtime-policy-new"),
    path("pay-setup/overtime/<int:pk>/", policies.overtime_policy_edit,
         name="overtime-policy-edit"),
    path("pay-setup/tax/", policies.tax_tables, name="tax-tables"),
    path("pay-setup/tax/new/", policies.tax_table_new, name="tax-table-new"),
    path("pay-setup/tax/<int:pk>/", policies.tax_table_edit, name="tax-table-edit"),
    path("pay-setup/insurance/", policies.insurance_rates, name="insurance-rates"),
    path("pay-setup/insurance/new/", policies.insurance_rate_new, name="insurance-rate-new"),
    path("pay-setup/insurance/<int:pk>/", policies.insurance_rate_edit,
         name="insurance-rate-edit"),
    path("pay-setup/holidays/", policies.holidays, name="holidays"),
    path("settings/activity/", audit.activity, name="activity"),
    path("settings/sign-ins/", iam.sign_ins, name="sign-ins"),
    path("settings/users/", iam.users, name="users"),
    path("settings/users/new/", iam.user_new, name="user-new"),
    path("settings/users/<int:pk>/", iam.user_edit, name="user-edit"),
    path("settings/roles/", iam.roles, name="roles"),
    path("settings/roles/new/", iam.role_new, name="role-new"),
    path("settings/roles/<int:pk>/", iam.role_edit, name="role-edit"),

    # The browser's JSON API (AJAX from static/core/js/api.js). /api/v1/ is kept free for the
    # mobile app, whose contract is PayRole's (phase 6).
    path("api/web/", include("config.api_urls")),
]
