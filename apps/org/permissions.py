from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions

register_permissions(_("Organisation"), [
    ("org.branch.view", _("View branches")),
    ("org.branch.manage", _("Manage branches")),
    ("org.settings.manage", _("Manage company settings")),
    ("org.department.view", _("View departments")),
    ("org.department.manage", _("Manage departments")),
])


DEPARTMENT_VIEW, DEPARTMENT_MANAGE = "org.department.view", "org.department.manage"
