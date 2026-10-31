"""The platform's own settings."""

from __future__ import annotations

from django.core.files.storage import default_storage

from apps.platform.tenants.models import PlatformSettings, WhatsAppService
from apps.platform.tenants.services import record


def save_platform_settings(row: PlatformSettings, *, old_logos: dict[str, str],
                           deleted_links: list, saved_links: list, changes: dict,
                           actor) -> PlatformSettings:
    """Save the branding and the sidebar links, and drop the logo files that were replaced."""
    row.save()
    for link in deleted_links:
        link.delete()
    for link in saved_links:
        link.save()
    PlatformSettings.objects.get(pk=1).save()  # drops the cached copy everywhere
    for name, old in old_logos.items():
        if old and old != getattr(row, name).name:
            default_storage.delete(old)
    record(actor, "platform.settings", None, **changes)
    return row


def save_whatsapp_settings(service: WhatsAppService, *, secret: str, changes: dict,
                           actor) -> WhatsAppService:
    """`secret` is a pasted key. Without one, a gateway switched on with no key is given one."""
    if secret:
        service.secret = secret
    elif service.enabled and not service.key:
        service.new_secret()
    service.save()
    record(actor, "whatsapp.settings", None, **changes)
    return service


def replace_whatsapp_key(service: WhatsAppService, *, actor) -> WhatsAppService:
    service.new_secret()
    service.save()
    record(actor, "whatsapp.key")
    return service
