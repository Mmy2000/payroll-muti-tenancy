from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import PAY, Feature, register_feature

register_permissions(_("Pay policies"), [
    ("policies.lateness.view", _("View lateness policies")),
    ("policies.lateness.manage", _("Manage lateness policies")),
    ("policies.overtime.view", _("View overtime policies")),
    ("policies.overtime.manage", _("Manage overtime policies")),
    ("policies.tax.view", _("View income tax tables")),
    ("policies.tax.manage", _("Manage income tax tables")),
    ("policies.insurance.view", _("View social insurance rates")),
    ("policies.insurance.manage", _("Manage social insurance rates")),
    ("policies.holiday.view", _("View public holidays")),
    ("policies.holiday.manage", _("Manage public holidays")),
])

# Lateness and overtime are measured on attendance: without it there is nothing to apply.
register_feature(Feature(
    "lateness", _("Lateness deductions"),
    _("Lateness policies with minute bands; late arrivals are deducted in payroll."),
    PAY, "alarm-clock", ("policies.lateness.",), requires=("attendance",)))
register_feature(Feature(
    "overtime", _("Overtime"),
    _("Overtime policies with minute bands; extra time is paid in payroll."),
    PAY, "timer", ("policies.overtime.",), requires=("attendance",)))
register_feature(Feature(
    "income_tax", _("Income tax"),
    _("Progressive income tax tables, deducted from pay."),
    PAY, "landmark", ("policies.tax.",)))
register_feature(Feature(
    "insurance", _("Social insurance"),
    _("Employee and employer insurance rates on the insured salary."),
    PAY, "shield-check", ("policies.insurance.",)))
register_feature(Feature(
    "public_holidays", _("Public holidays"),
    _("Paid days off for every branch or one branch."),
    PAY, "calendar-days", ("policies.holiday.",), requires=("attendance",)))
