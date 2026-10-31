from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import PAY, Feature, register_feature

register_permissions(_("Pay items"), [
    ("compensation.item.view", _("View pay items")),
    ("compensation.item.manage", _("Manage pay items")),
    ("compensation.entry.view", _("View the pay items given to employees")),
    ("compensation.entry.manage", _("Give pay items to employees and cancel them")),
])

register_feature(Feature(
    "pay_items", _("Allowances and pay items"),
    _("Allowances and other additions and deductions, fixed or per day worked."),
    PAY, "hand-coins", ("compensation.",)))


GIVE = "compensation.entry.manage"
