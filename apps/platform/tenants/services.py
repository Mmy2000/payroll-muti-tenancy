"""Each staff act leaves a PlatformEvent."""

from __future__ import annotations

from .models import (
    PlatformEvent,
    Tenant,
)


def record(actor, action: str, tenant: Tenant | None = None, **detail) -> None:
    PlatformEvent.objects.create(actor=actor, tenant=tenant, action=action,
                                 detail={k: str(v) for k, v in detail.items()})


