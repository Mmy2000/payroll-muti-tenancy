from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions

register_permissions(_("Organisation"), [
    ("org.branch.view", _("View branches")),
    ("org.branch.manage", _("Manage branches")),
    ("org.settings.manage", _("Manage company settings")),
    ("org.department.view", _("View departments")),
    ("org.department.manage", _("Manage departments")),
    ("org.position.view", _("View positions")),
    ("org.position.manage", _("Manage positions")),
], company_wide=("org.settings.manage", "org.position.manage"))


BRANCH_MANAGE = "org.branch.manage"
DEPARTMENT_VIEW, DEPARTMENT_MANAGE = "org.department.view", "org.department.manage"
POSITION_VIEW, POSITION_MANAGE = "org.position.view", "org.position.manage"
