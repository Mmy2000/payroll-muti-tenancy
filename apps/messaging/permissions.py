from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import TOOLS, Feature, register_feature

register_permissions(_("WhatsApp"), [
    ("messaging.view", _("See the WhatsApp messages sent")),
    ("messaging.send", _("Send payslips on WhatsApp")),
    ("messaging.whatsapp.link", _("Link the company's WhatsApp number and set its wording")),
])

register_feature(Feature(
    "whatsapp", _("WhatsApp"),
    _("Payslips sent on WhatsApp from the company's own number."),
    TOOLS, "send", ("messaging.",), default=False))
