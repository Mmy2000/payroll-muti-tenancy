from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import PEOPLE, Feature, register_feature

register_permissions(_("Evaluations"), [
    ("evaluations.evaluation.view", _("See evaluations")),
    ("evaluations.evaluation.manage", _("Write evaluations")),
])

register_feature(Feature(
    "evaluations", _("Evaluations"),
    _("A yearly evaluation of each employee, with notes and a printed card."),
    PEOPLE, "clipboard-check", ("evaluations.",)))
