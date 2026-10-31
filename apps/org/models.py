"""Organisation structure of a tenant: its profile and branches."""

from __future__ import annotations

import zoneinfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.media import TenantUploadPath, validate_image
from apps.core.models import TenantScopedModel


def validate_timezone(value: str) -> None:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"Unknown time zone: {value}") from exc


class TenantProfile(TenantScopedModel):
    """The tenant's business identity and locale. Replaces PayRole's singleton `com` and its
    global settings (time zone, phone region)."""

    display_name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    tax_registration_no = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp_number = models.CharField(max_length=30, blank=True)
    logo = models.FileField(upload_to=TenantUploadPath("branding"), blank=True,
                            validators=[validate_image])
    functional_currency = models.CharField(max_length=3, default="EGP")
    timezone = models.CharField(max_length=64, default="Africa/Cairo",
                                validators=[validate_timezone])
    locale = models.CharField(max_length=8, default="ar", choices=settings.LANGUAGES)
    country = models.CharField(max_length=2, default="EG")  # ISO 3166; phone number region
    # Accent colour of the workspace (apps.core.appearance.ACCENTS); users may pick their own.
    accent = models.CharField(max_length=16, default="teal")
    # How long a QR for signing in to the app works (apps/mobile/services/qr.py), at most a week.
    app_qr_minutes = models.PositiveIntegerField(default=15)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="org_tenantprofile_tenant_uniq"),
        ]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.core.cache import cache

        from apps.core import timezones
        from apps.core.i18n import tenant_locale_cache_key

        cache.delete(tenant_locale_cache_key(self.tenant_id))
        timezones.forget(self.tenant_id)


class Branch(TenantScopedModel):
    """An office or site. PayRole: `Enp.Br1` (`br` → code, `brna` → name)."""

    code = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)
    is_head_office = models.BooleanField(default=False)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    # Where it is, for punches from the mobile app inside its area (the geofence feature).
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_m = models.PositiveIntegerField(default=200)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="org_branch_code_uniq"),
            models.UniqueConstraint(
                fields=["tenant"], condition=Q(is_head_office=True),
                name="org_branch_one_head_office_uniq",
            ),
            models.CheckConstraint(condition=Q(code__gte=1, code__lte=999),
                                   name="org_branch_code_range_check"),
        ]

    def __str__(self):
        return f"{self.code:02d} {self.name}"


class Department(TenantScopedModel):
    """A group of employees in one branch (PayRole: `Enp.Pfn`, "المجموعة", with its `br1`). The
    same name may be used in several branches: each is its own department, with its own code."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="departments")
    code = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["branch__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "branch", "code"],
                                    name="org_department_code_uniq"),
            models.UniqueConstraint(fields=["tenant", "branch", "name"],
                                    name="org_department_name_uniq"),
        ]

    def __str__(self):
        return self.name

    @property
    def label(self) -> str:
        """For lists across branches, where two departments may have the same name."""
        return f"{self.name} · {self.branch.name}"
