from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import ATTENDANCE, Feature, register_feature

register_permissions(_("Attendance"), [
    ("attendance.day.view", _("View attendance")),
    ("attendance.day.manage", _("Enter and correct attendance")),
    ("attendance.import", _("Import attendance from Excel")),
    ("attendance.leave.view", _("View leave requests and balances")),
    ("attendance.leave.request", _("Enter leave requests")),
    ("attendance.leave.approve", _("Approve, reject and cancel leave")),
    ("attendance.leave_type.manage", _("Manage leave types")),
    ("attendance.hourly.view", _("View hourly leave")),
    ("attendance.hourly.request", _("Enter hourly leave")),
    ("attendance.hourly.approve", _("Approve, reject and cancel hourly leave")),
])

register_feature(Feature(
    "attendance", _("Attendance"),
    _("Who came and when: the daily sheet, manual entries, absences and days off."),
    ATTENDANCE, "clock", ("attendance.day.",)))
register_feature(Feature(
    "attendance_import", _("Attendance import"),
    _("Clock times from an Excel file."),
    ATTENDANCE, "file-spreadsheet", ("attendance.import",), requires=("attendance",)))
register_feature(Feature(
    "leave", _("Leave"),
    _("Leave types, requests with approval, and the yearly balance."),
    ATTENDANCE, "calendar-days", ("attendance.leave.", "attendance.leave_type."),
    requires=("attendance",)))
register_feature(Feature(
    "hourly_leave", _("Hourly leave"),
    _("A few hours away within a day, up to a monthly allowance."),
    ATTENDANCE, "calendar-clock", ("attendance.hourly.",), requires=("attendance",)))
