"""A phone linked to the employee's fingerprint, and the proof it sends with each punch."""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.crypto import decrypt, encrypt
from apps.employees.models import Employee

from ..contract import AppError
from ..domain.proof import PROOF_WINDOW_SECONDS, expected_proof, proof_time
from ..models import BiometricEnrollment, BiometricNonce
from ..selectors import active_enrollment

NONCE_KEEP_SECONDS = PROOF_WINDOW_SECONDS * 5


def enroll(employee: Employee, device_id: str, app_version: str = "") -> tuple:
    """A new phone for the employee's proofs; the earlier one stops working. Returns the
    enrollment and its secret (given once)."""
    now = timezone.now()
    with transaction.atomic():
        BiometricEnrollment.objects.filter(employee=employee, is_active=True).update(
            is_active=False, revoked_at=now, revoked_reason="reenroll")
        secret = secrets.token_hex(32)
        enrollment = BiometricEnrollment.objects.create(
            employee=employee, device_id=device_id, secret_encrypted=encrypt(secret),
            app_version=app_version)
    return enrollment, secret


def revoke(employee: Employee, reason: str = "signout") -> int:
    return BiometricEnrollment.objects.filter(employee=employee, is_active=True).update(
        is_active=False, revoked_at=timezone.now(), revoked_reason=reason)


def verify_proof(employee: Employee, direction: int, device_id: str, proof: dict | None) -> None:
    enrollment = active_enrollment(employee)
    if enrollment is None:
        raise AppError("biometric_not_enrolled")
    if not proof:
        raise AppError("biometric_required")
    if proof["enrollment_id"] != enrollment.pk:
        raise AppError("biometric_revoked")
    if (device_id or "") != enrollment.device_id:
        raise AppError("biometric_device_mismatch")
    stamped = proof_time(proof["timestamp"])
    now = timezone.now()
    if stamped is None or abs((now - stamped).total_seconds()) > PROOF_WINDOW_SECONDS:
        raise AppError("biometric_stale")
    expected = expected_proof(decrypt(enrollment.secret_encrypted), enrollment.pk,
                              enrollment.device_id, direction, proof["timestamp"],
                              proof["nonce"])
    if not hmac.compare_digest(expected, proof["proof"]):
        raise AppError("biometric_invalid")
    BiometricNonce.objects.filter(used_at__lt=now - timedelta(seconds=NONCE_KEEP_SECONDS)
                                  ).delete()
    try:
        with transaction.atomic():
            BiometricNonce.objects.create(enrollment=enrollment, nonce=proof["nonce"])
    except IntegrityError:
        raise AppError("biometric_replay") from None
    enrollment.last_used_at = now
    enrollment.save(update_fields=["last_used_at", "updated_at"])
