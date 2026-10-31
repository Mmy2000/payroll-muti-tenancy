from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import ATTENDANCE, Feature, register_feature

register_permissions(_("Fingerprint devices"), [
    ("devices.device.view", _("See fingerprint devices and what they sent")),
    ("devices.device.manage", _("Set up fingerprint devices and link their users")),
])

register_feature(Feature(
    "zk_devices", _("Fingerprint devices"),
    _("ZKTeco devices sending punches to the system (ADMS), linked to employees."),
    ATTENDANCE, "fingerprint", ("devices.",), default=False, requires=("attendance",)))


VIEW, MANAGE = "devices.device.view", "devices.device.manage"
