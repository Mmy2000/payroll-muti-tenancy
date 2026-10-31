"""Signing in to the app by scanning a QR code, so nobody types an address or a password.

The QR holds the client's address and a long random code, never a credential: the code works
once, for minutes, and only its fingerprint is stored, so the database can't give a code away
and a QR can't be drawn again later. Renewing gives the QR on screen more time; a new one
replaces it. One active code per employee, and every step is in the History.

Issuing a code is signing someone in, so it follows the rule for setting a password: nobody can
do it for a person with more powers than their own (a manager, for an owner who is an employee).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import segno
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import DomainError, NotFound
from apps.employees.selectors import get_employee
from apps.iam import services as iam
from apps.iam import validators as iam_validators
from apps.iam.authz import build_actor
from apps.org.models import TenantProfile

from . import access, devices
from .contract import AppError
from .devices import MANAGE  # noqa: F401 (the web API's permission)
from .models import AppLinkCode, DeviceMethod

CODE_BYTES = 32  # far beyond guessing: the limit on tries is only there to stop abuse
SIGNIN = "mobile.signin"


@dataclass(frozen=True)
class Issued:
    code: str  # shown once: only its fingerprint is kept
    link: AppLinkCode


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _expires_at():
    minutes = TenantProfile.objects.values_list("app_qr_minutes", flat=True).first() or 15
    return timezone.now() + timedelta(minutes=minutes)


def _usable():
    return AppLinkCode.objects.filter(used_at__isnull=True, cancelled_at__isnull=True,
                                      expires_at__gt=timezone.now())


def active(employee) -> AppLinkCode | None:
    return _usable().filter(employee=employee).first()


def _new_login(employee):
    """The employee's app login, when they have none: no password anyone knows, since they
    get in by the QR."""
    username = f"emp{employee.code}"
    if iam.Membership.objects.filter(username=username).exists():
        username = f"emp{employee.code}-{employee.pk}"
    return access.give_login(employee.pk, username, secrets.token_urlsafe(32))


def _ready_member(employee, actor):
    if not employee.is_active:
        raise DomainError(_("This employee has left."), code="MOBILE_QR_LEFT")
    member = employee.member
    if member is None:
        return _new_login(employee)
    iam_validators.ensure_can_act_on(member, actor)
    if member.status != iam.MembershipStatus.ACTIVE:
        raise DomainError(_("This employee's login is suspended."), code="MOBILE_QR_SUSPENDED")
    if not build_actor(member).can(SIGNIN):
        raise DomainError(_("This user's role doesn't allow the mobile app."),
                          code="MOBILE_QR_NO_APP")
    return member


def _employee(employee_id: int, actor):
    employee = get_employee(employee_id, actor, MANAGE, lock=True)
    if actor is not None:
        actor.require(MANAGE, branch=employee.branch_id)
    return employee


def issue(employee_id: int, *, actor=None) -> Issued:
    """A new QR. The one before it stops working."""
    with transaction.atomic():
        employee = _employee(employee_id, actor)
        member = _ready_member(employee, actor)
        _usable().filter(employee=employee).update(cancelled_at=timezone.now())
        code = secrets.token_urlsafe(CODE_BYTES)
        link = AppLinkCode.objects.create(
            employee=employee, member=member, code_hash=_digest(code), expires_at=_expires_at(),
            issued_by=getattr(actor, "user", None))
    return Issued(code, link)


def renew(employee_id: int, *, actor=None) -> AppLinkCode:
    """More time for the QR already handed out."""
    with transaction.atomic():
        employee = _employee(employee_id, actor)
        link = _usable().select_for_update().filter(employee=employee).first()
        if link is None:
            raise NotFound(_("This QR is no longer valid. Generate a new one."))
        link.expires_at = _expires_at()
        link.save(update_fields=["expires_at", "updated_at"])
    return link


def cancel(employee_id: int, *, actor=None) -> int:
    with transaction.atomic():
        employee = _employee(employee_id, actor)
        return _usable().filter(employee=employee).update(cancelled_at=timezone.now())


def redeem(code: str, device_id: str):
    """The app's scan: the member and their phone. The code is spent, whatever comes next."""
    with transaction.atomic():
        link = (AppLinkCode.objects.select_for_update().select_related("member", "employee")
                .filter(code_hash=_digest(code)).first())
        if link is None or link.cancelled_at is not None:
            raise AppError("qr_invalid")
        if link.used_at is not None:
            raise AppError("qr_used")
        if link.expires_at <= timezone.now():
            raise AppError("qr_expired")
        member = link.member
        if (link.employee.member_id != member.pk or member.status != iam.MembershipStatus.ACTIVE
                or not build_actor(member).can(SIGNIN)):
            raise AppError("qr_invalid")
        device = devices.sign_in(member, device_id, DeviceMethod.QR)
        link.used_at, link.used_device = timezone.now(), device
        link.save(update_fields=["used_at", "used_device", "updated_at"])
    return member, device


def link_text(base_url: str, code: str) -> str:
    """What the QR says. It opens the app when scanned by the phone's own camera too."""
    return "payroll://link?" + urlencode({"url": base_url, "code": code})


def qr_svg(text: str) -> str:
    return segno.make(text, error="m").svg_inline(scale=5, border=2, dark="#000", light="#fff")
