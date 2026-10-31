"""The fingerprint proof a phone sends with a punch: what it must equal."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime

from django.utils import timezone

PROOF_WINDOW_SECONDS = 120


def proof_time(text: str) -> datetime | None:
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return timezone.make_aware(datetime.strptime(text, pattern))
        except ValueError:
            continue
    return None


def expected_proof(secret: str, enrollment_id: int, device_id: str, direction: int,
                   timestamp: str, nonce: str) -> str:
    message = f"{enrollment_id}|{device_id}|{direction}|{timestamp}|{nonce}"
    return hmac.new(bytes.fromhex(secret), message.encode(), hashlib.sha256).hexdigest()
