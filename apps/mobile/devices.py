"""The phones signed in to the app, one record each, so one phone can be signed out without
touching the person's other phones or their login.

A sign-in names its phone in the tokens (the `did` claim, apps/mobile/api/v1/auth.py). Every
request and token refresh then checks that phone is still allowed, which is what makes signing
it out take effect at once rather than when its 30-day token runs out. An older app sends no
device id and gets tokens without the claim; they work as they always did.
"""

from __future__ import annotations

from django.db.models import QuerySet
from django.utils import timezone

from apps.core.errors import NotFound

from .models import AppDevice, BiometricEnrollment

MANAGE = "mobile.qr.manage"


def sign_in(member, device_id: str, method: str) -> AppDevice | None:
    """The phone's record, allowed again if it had been signed out."""
    if not device_id:
        return None
    device, _created = AppDevice.objects.update_or_create(
        member=member, device_id=device_id,
        defaults={"method": method, "signed_in_at": timezone.now(), "revoked_at": None,
                  "revoked_by": None})
    return device


def is_allowed(device_pk: int) -> bool:
    return AppDevice.objects.filter(pk=device_pk, revoked_at__isnull=True).exists()


def seen(device_pk: int) -> None:
    AppDevice.objects.filter(pk=device_pk).update(last_seen_at=timezone.now())


def signed_in(member) -> QuerySet:
    return AppDevice.objects.filter(member=member, revoked_at__isnull=True)


def revoke(device_pk: int, *, actor=None) -> AppDevice:
    """Sign one phone out, at once. Its fingerprint link goes with it."""
    from apps.employees.models import Employee

    device = AppDevice.objects.filter(pk=device_pk, revoked_at__isnull=True).first()
    if device is None:
        raise NotFound("Not found.")
    employee = Employee.objects.filter(member_id=device.member_id).first()
    if actor is not None:
        actor.require(MANAGE, branch=employee.branch_id if employee else None)
    device.revoked_at = timezone.now()
    device.revoked_by = getattr(actor, "user", None)
    device.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
    if employee is not None:
        BiometricEnrollment.objects.filter(employee=employee, device_id=device.device_id,
                                           is_active=True).update(
            is_active=False, revoked_at=timezone.now(), revoked_reason="manual")
    return device
