"""URLs served on tenant hosts. The Django admin is deliberately absent (platform host only).

Each phase adds its screens here; their JSON endpoints go in config/api_urls.py."""

from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.adjustments.web import views as adjustments
from apps.attendance.web import views as attendance
from apps.audit.web import views as audit
from apps.compensation.web import views as compensation
from apps.core import media
from apps.devices import iclock
from apps.devices.web import views as devices
from apps.employees.web import views as employees
from apps.evaluations.web import views as evaluations
from apps.iam.web import views as iam
from apps.iam.web.forms import WorkspaceLoginForm
from apps.loans.web import views as loans
from apps.messaging.web import views as messaging
from apps.notifications.web import views as notifications
from apps.org.web import company
from apps.org.web import views as org
from apps.payroll.web import views as payroll
from apps.policies.web import views as policies
from apps.reports.web import views as reports

urlpatterns = [
    # Fingerprint devices (ZKTeco ADMS) call these, as PayRole served them: no trailing slash.
    path("iclock/cdata", iclock.cdata, name="iclock-cdata"),
    path("iclock/getrequest", iclock.getrequest, name="iclock-getrequest"),
    path("iclock/devicecmd", iclock.devicecmd, name="iclock-devicecmd"),

    path("", reports.home, name="home"),
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
    path("positions/", org.positions, name="positions"),
    path("positions/new/", org.position_new, name="position-new"),
    path("positions/<int:pk>/", org.position_edit, name="position-edit"),

    path("employees/", employees.employees, name="employees"),
    path("employees/new/", employees.employee_new, name="employee-new"),
    path("employees/import/", employees.employee_import, name="employee-import"),
    path("employees/import/template.xlsx", employees.employee_import_template,
         name="employee-import-template"),
    path("employees/hours/", employees.hours_group, name="employees-hours"),
    path("people/evaluations/", evaluations.evaluations, name="evaluations"),
    path("people/evaluations/new/", evaluations.evaluation_new, name="evaluation-new"),
    path("people/evaluations/<int:pk>/", evaluations.evaluation, name="evaluation"),
    path("people/evaluations/<int:pk>/card.pdf", evaluations.evaluation_pdf,
         name="evaluation-pdf"),
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
    path("attendance/hourly/group/", attendance.hourly_leave_group,
         name="hourly-leave-for-group"),
    path("attendance/by-hand/", attendance.times_group, name="attendance-times"),
    path("attendance/devices/", devices.devices, name="devices"),
    path("attendance/devices/<int:pk>/", devices.device, name="device"),

    path("pay/advances/", loans.advance_list, name="advances"),
    path("pay/loans/", loans.loan_list, name="loans"),
    path("pay/loans/new/", loans.loan_new, name="loan-new"),
    path("pay/loans/<int:pk>/", loans.loan_detail, name="loan"),
    path("pay/incentives/", adjustments.incentives, name="incentives"),
    path("pay/incentives/new/", adjustments.incentive_new, name="incentive-new"),
    path("pay/incentives/types/", adjustments.incentive_types, name="incentive-types"),
    path("pay/incentives/<int:pk>/", adjustments.incentive_batch, name="incentive-batch"),
    path("pay/penalties/", adjustments.penalties, name="penalties"),
    path("pay/penalties/new/", adjustments.penalty_new, name="penalty-new"),
    path("pay/penalties/types/", adjustments.penalty_types, name="penalty-types"),
    path("pay/penalties/<int:pk>/", adjustments.penalty_batch, name="penalty-batch"),
    path("pay/items/", compensation.assignments, name="pay-item-assignments"),
    path("pay/items/new/", compensation.assignment_new, name="pay-item-assignment-new"),

    path("payroll/", payroll.runs, name="payroll-runs"),
    path("payroll/new/", payroll.run_new, name="payroll-run-new"),
    path("payroll/<int:pk>/", payroll.run_detail, name="payroll-run"),
    path("payroll/<int:pk>/payslips/<int:slip_pk>/", payroll.payslip_detail, name="payslip"),
    path("payroll/<int:pk>/payslips.pdf", payroll.run_payslips_pdf, name="payroll-payslips-pdf"),
    path("payroll/<int:pk>/payslips/<int:slip_pk>/pdf/", payroll.payslip_pdf,
         name="payslip-pdf"),

    path("pay-setup/calendars/", payroll.calendars, name="pay-calendars"),

    path("reports/", reports.index, name="reports"),
    path("reports/<slug:code>/", reports.run_report, name="report"),
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
    path("notifications/", notifications.notifications, name="notifications"),
    path("notifications/stream/", notifications.stream, name="notifications-stream"),
    path("settings/whatsapp/", messaging.whatsapp, name="whatsapp"),
    path("settings/messages/", messaging.messages, name="sent-messages"),
    path("settings/sign-ins/", iam.sign_ins, name="sign-ins"),
    path("settings/users/", iam.users, name="users"),
    path("settings/users/new/", iam.user_new, name="user-new"),
    path("settings/users/<int:pk>/", iam.user_edit, name="user-edit"),
    path("settings/roles/", iam.roles, name="roles"),
    path("settings/roles/new/", iam.role_new, name="role-new"),
    path("settings/roles/<int:pk>/", iam.role_edit, name="role-edit"),

    # The browser's JSON API (AJAX from static/core/js/api.js), and the mobile app's, whose
    # contract is PayRole's (docs/mobile-api.md).
    path("api/web/", include("config.api_urls")),
    path("api/v1/", include("apps.mobile.api.v1.urls")),
]
