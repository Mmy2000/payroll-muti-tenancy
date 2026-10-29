from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import PAY, Feature, register_feature

register_permissions(_("Incentives and penalties"), [
    ("adjustments.incentive.view", _("View incentives")),
    ("adjustments.incentive.manage", _("Give incentives and edit drafts, and their types")),
    ("adjustments.incentive.approve",
     _("Approve incentives, and reopen, cancel or correct approved ones")),
    ("adjustments.penalty.view", _("View penalties")),
    ("adjustments.penalty.manage", _("Give penalties and edit drafts, and their types")),
    ("adjustments.penalty.approve",
     _("Approve penalties, and reopen, cancel or correct approved ones")),
])

register_feature(Feature(
    "incentives", _("Incentives"),
    _("Incentives for an employee, a department or a branch, added to pay."),
    PAY, "award", ("adjustments.incentive.",)))
register_feature(Feature(
    "penalties", _("Penalties"),
    _("Penalties for an employee, a department or a branch, deducted from pay."),
    PAY, "gavel", ("adjustments.penalty.",)))
