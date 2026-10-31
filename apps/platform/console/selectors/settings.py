"""The platform's own settings, as the console edits them."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.platform.tenants.models import PlatformLink, PlatformSettings


def settings_row() -> PlatformSettings:
    return PlatformSettings.objects.filter(pk=1).first() or PlatformSettings(pk=1)


def platform_links() -> QuerySet[PlatformLink]:
    return PlatformLink.objects.all()
