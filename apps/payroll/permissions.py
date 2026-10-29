from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions

# Payroll is the core of the product: no feature switches it off. Reading runs shows everyone's
# pay, so it is a permission of its own (not ".view", which the read-only Viewer role gets).
register_permissions(_("Payroll"), [
    ("payroll.run.read", _("See payroll runs and payslips")),
    ("payroll.run.calculate", _("Calculate payroll runs and add lines to payslips")),
    ("payroll.run.approve", _("Approve payroll runs")),
    ("payroll.run.pay", _("Record that a payroll run was paid")),
    ("payroll.run.reverse", _("Reverse an approved payroll run")),
    ("payroll.calendar.manage", _("Set up pay calendars")),
])
