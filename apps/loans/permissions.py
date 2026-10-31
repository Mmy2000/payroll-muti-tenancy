from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import PAY, Feature, register_feature

register_permissions(_("Advances and loans"), [
    ("loans.advance.view", _("View salary advances")),
    ("loans.advance.manage", _("Give and cancel salary advances")),
    ("loans.loan.view", _("View loans")),
    ("loans.loan.manage", _("Grant, postpone and cancel loans")),
])

register_feature(Feature(
    "advances", _("Salary advances"),
    _("Part of a month's pay given early, recovered by that month's payroll."),
    PAY, "hand-coins", ("loans.advance.",)))
register_feature(Feature(
    "loans", _("Loans"),
    _("Loans recovered in monthly installments, with postponing."),
    PAY, "piggy-bank", ("loans.loan.",)))


VIEW, MANAGE = "loans.loan.view", "loans.loan.manage"
