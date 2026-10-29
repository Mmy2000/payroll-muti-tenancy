"""Reports read with the permission of the data they show (apps/reports/registry.py); exporting
them as PDF or Excel is a permission and a feature of its own. Importing the report modules here
fills the registry when the permission catalog is built."""

from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import TOOLS, Feature, register_feature

from . import catalog  # noqa: F401  (registers every report)

register_permissions(_("Reports"), [
    ("reports.export", _("Download reports as PDF or Excel")),
])

register_feature(Feature(
    "reports_export", _("Report export"),
    _("Reports downloaded as PDF or Excel (they can always be read and printed on screen)."),
    TOOLS, "file-down", ("reports.export",)))
