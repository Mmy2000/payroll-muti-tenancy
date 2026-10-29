from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions

# Employees are the core of the product: no feature switches them off.
# Pay has permissions of its own, and neither ends in ".view", so the read-only Viewer role
# does not see what anyone earns.
register_permissions(_("Employees"), [
    ("employees.employee.view", _("View employees")),
    ("employees.employee.manage", _("Add and edit employees, their hours and departures")),
    ("employees.employee.import", _("Import employees from Excel")),
    ("employees.salary.read", _("See employees' pay")),
    ("employees.salary.manage", _("Set and change employees' pay")),
])
