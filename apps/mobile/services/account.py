"""What a member changes about themselves from the app: their last sign-in, password and
employee details."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from .. import contract
from ..contract import AppError


def mark_signed_in(user) -> None:
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])


def change_password(user, current: str, new: str) -> None:
    if not user.check_password(current):
        raise AppError("wrong_password")
    if current == new:
        raise AppError("same_password")
    try:
        validate_password(new, user)
    except DjangoValidationError as exc:
        found = [arabic for english, arabic in contract.WEAK.items()
                 if any(english in str(m) for m in exc.messages)]
        raise AppError("weak_password", detail=" · ".join(found) or
                       contract.MESSAGES["weak_password"]) from None
    user.set_password(new)
    user.save(update_fields=["password"])


@dataclass(frozen=True)
class ProfileInput:
    """None: not sent, left as it is."""

    phone: str | None = None
    address: str | None = None
    photo: object = None  # an uploaded file


def update_profile(person, data: ProfileInput, *, by) -> None:
    fields = []
    if data.phone is not None:
        person.phone, fields = data.phone, [*fields, "phone"]
    if data.address is not None:
        person.address, fields = data.address, [*fields, "address"]
    old = ""
    if data.photo is not None:
        old = person.photo.name if person.photo else ""
        person.photo.save(data.photo.name, data.photo, save=False)
        fields.append("photo")
    if not fields:
        raise AppError("nothing_to_update")
    person.updated_by = by
    person.save(update_fields=[*fields, "updated_by", "updated_at"])
    if old:
        transaction.on_commit(lambda: person.photo.storage.delete(old))
