"""The mobile app's own records (PayRole `zkk.BiometricEnrollment`, `BiometricNonce`,
`TrackSession`, `TrackPoint`): which phone proves the employee's fingerprint, and where the
employee went during a shift. Punches themselves are attendance punches (source "mobile").
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class BiometricEnrollment(TenantScopedModel):
    """The phone whose fingerprint check vouches for the employee's punches: one at a time.
    The shared secret is encrypted at rest (PayRole kept it in plain text)."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE,
                                 related_name="+")
    device_id = models.CharField(max_length=100)
    secret_encrypted = models.TextField()
    app_version = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    enrolled_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=10, blank=True)  # reenroll / signout / manual

    class Meta:
        ordering = ["-enrolled_at"]
        indexes = [models.Index(fields=["tenant", "employee", "is_active"],
                                name="mobile_enrollment_active_idx")]


class DeviceMethod(models.TextChoices):
    QR = "qr", _("QR code")
    PASSWORD = "password", _("Password")


class AppDevice(TenantScopedModel):
    """A phone signed in to the app (apps/mobile/devices.py)."""

    member = models.ForeignKey("iam.Membership", on_delete=models.CASCADE,
                               related_name="app_devices")
    device_id = models.CharField(max_length=100)
    method = models.CharField(max_length=10, choices=DeviceMethod.choices)
    signed_in_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-signed_in_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "member", "device_id"],
                                               name="mobile_device_once_uniq")]


class AppLinkCode(TenantScopedModel):
    """A QR for signing in (apps/mobile/qr.py). Only the code's fingerprint is kept."""

    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE,
                                 related_name="+")
    member = models.ForeignKey("iam.Membership", on_delete=models.CASCADE, related_name="+")
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_device = models.ForeignKey(AppDevice, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code_hash"],
                                               name="mobile_link_code_uniq")]
        indexes = [models.Index(fields=["tenant", "employee", "expires_at"],
                                name="mobile_link_active_idx")]


class BiometricNonce(TenantScopedModel):
    """A proof's one-time value: the same proof twice is a replay."""

    enrollment = models.ForeignKey(BiometricEnrollment, on_delete=models.CASCADE,
                                   related_name="+")
    nonce = models.CharField(max_length=64)
    used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "enrollment", "nonce"],
                                               name="mobile_nonce_once_uniq")]


class EndReason(models.TextChoices):
    CHECKOUT = "checkout", _("Checked out")
    TIMEOUT = "timeout", _("Stopped by itself")
    MANUAL = "manual", _("Stopped by hand")


class TrackSession(TenantScopedModel):
    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE,
                                 related_name="+")
    branch = models.ForeignKey("org.Branch", on_delete=models.PROTECT, related_name="+")
    check_in = models.ForeignKey("attendance.Punch", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    check_out = models.ForeignKey("attendance.Punch", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    end_reason = models.CharField(max_length=10, choices=EndReason.choices, blank=True)
    device_id = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=20, blank=True)
    total_distance_m = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    points_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["tenant", "employee", "started_at"],
                                name="mobile_session_emp_idx"),
                   models.Index(fields=["tenant", "is_active"], name="mobile_session_active_idx")]

    @property
    def duration_minutes(self) -> int:
        end = self.ended_at or timezone.now()
        return max(int((end - self.started_at).total_seconds() // 60), 0)


class TrackPoint(TenantScopedModel):
    session = models.ForeignKey(TrackSession, on_delete=models.CASCADE, related_name="points")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    speed = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    heading = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    battery = models.IntegerField(null=True, blank=True)
    recorded_at = models.DateTimeField()  # the phone's time
    received_at = models.DateTimeField(default=timezone.now)
    is_mock = models.BooleanField(default=False)

    class Meta:
        ordering = ["recorded_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "session", "recorded_at"],
                                               name="mobile_point_moment_uniq")]
