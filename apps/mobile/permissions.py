from django.utils.translation import gettext_lazy as _

from apps.iam.catalog import register_permissions
from apps.platform.tenants.features import ATTENDANCE, Feature, register_feature

# Following where people went is not a ".view": the read-only Viewer role must not get it.
register_permissions(_("Mobile app"), [
    ("mobile.signin", _("Use the mobile app")),
    ("mobile.monitor.track", _("Follow employees' routes and live positions")),
])

register_feature(Feature(
    "mobile_app", _("Mobile app"),
    _("Employees punch, ask for leave and read their notifications in the app."),
    ATTENDANCE, "smartphone", ("mobile.",), default=False, requires=("attendance",)))
# These change how the app's punches are checked; they own no permissions of their own.
register_feature(Feature(
    "biometric", _("Fingerprint on the phone"),
    _("A punch from the app needs the phone's fingerprint check, on the employee's own phone."),
    ATTENDANCE, "fingerprint", (), default=False, requires=("mobile_app",)))
register_feature(Feature(
    "gps_tracking", _("GPS tracking"),
    _("The app sends where the employee is during the shift; a check-in needs it switched "
      "on."), ATTENDANCE, "map-pin", (), default=False, requires=("mobile_app",)))
register_feature(Feature(
    "geofence", _("Punch inside the branch"),
    _("A punch from the app is refused outside the branch's area (its location and radius)."),
    ATTENDANCE, "map-pin", (), default=False, requires=("mobile_app",)))
