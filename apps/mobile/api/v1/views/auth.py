"""Signing in, by password or by QR, and tokens."""

from __future__ import annotations

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.iam import throttle
from apps.iam.authz import build_actor
from apps.iam.catalog import WILDCARD
from apps.iam.signals import client_ip

from .... import contract, selectors
from ....contract import AppError
from ....models import DeviceMethod
from ....services import devices, qr
from .. import serializers as s
from ..auth import DEVICE_CLAIM, active_membership, tokens_for
from .base import MONITOR, SIGNIN, AppView, EnglishMixin, valid


def _role(actor) -> str | None:
    if WILDCARD in actor.grants:
        return "owner"
    codes = set(actor.grants) - {SIGNIN}
    if not codes:
        return "employee"
    return "staff"


def employee_or_none(member):
    try:
        return selectors.employee_of(member)
    except AppError:
        return None


def _signed_in(member, device, request) -> dict:
    """The answer to a sign-in, by password or by QR."""
    user, actor = member.user, build_actor(member)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return {**tokens_for(member, device.pk if device else None), "username": member.username,
            "role": _role(actor), "is_superuser": actor.can(MONITOR),
            "employee": s.employee(employee_or_none(member), request)}


class LoginView(EnglishMixin, APIView):
    authentication_classes = ()
    permission_classes = ()

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'  # a wrong password is 401, as SimpleJWT's own views say

    def post(self, request):
        data = valid(s.LoginSerializer, request.data)
        username = data["username"].strip()
        user = authenticate(request._request, username=username, password=data["password"])
        member = active_membership(user) if user is not None else None
        actor = build_actor(member) if member is not None else None
        if member is None or not actor.can(SIGNIN):
            raise exceptions.AuthenticationFailed(  # DRF's own: no "code", as PayRole
                "No active account found with the given credentials")
        throttle.succeeded(request._request, username)
        device = devices.sign_in(member, data["device_id"], DeviceMethod.PASSWORD)
        return Response(_signed_in(member, device, request))


class QrLoginView(EnglishMixin, APIView):
    """The app's scan: a one-time code for the same answer as a login."""

    authentication_classes = ()
    permission_classes = ()

    def post(self, request):
        data = valid(s.QrLoginSerializer, request.data)
        tries = f"qr:{client_ip(request._request)}"
        if throttle.locked_for(request._request, tries):
            raise AppError("qr_locked", status=429)
        try:
            member, device = qr.redeem(data["code"], data["device_id"])
        except AppError as error:
            if error.code == "qr_invalid":  # guessing; an old QR scanned by mistake isn't
                throttle.failed(request._request, tries)
            raise
        return Response(_signed_in(member, device, request))


class RefreshView(EnglishMixin, TokenRefreshView):
    serializer_class = s.TenantRefreshSerializer


class VerifyView(EnglishMixin, TokenVerifyView):
    pass


class ChangePasswordView(AppView):
    def post(self, request):
        data = valid(s.ChangePasswordSerializer, request.data)
        user = request.user
        if not user.check_password(data["current_password"]):
            raise AppError("wrong_password")
        if data["current_password"] == data["new_password"]:
            raise AppError("same_password")
        try:
            validate_password(data["new_password"], user)
        except DjangoValidationError as exc:
            found = [arabic for english, arabic in contract.WEAK.items()
                     if any(english in str(m) for m in exc.messages)]
            raise AppError("weak_password", detail=" · ".join(found) or
                           contract.MESSAGES["weak_password"]) from None
        user.set_password(data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": contract.PASSWORD_CHANGED,
                         **tokens_for(self.member, request.auth.get(DEVICE_CLAIM))})
