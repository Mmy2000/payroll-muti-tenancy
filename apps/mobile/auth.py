"""Signing in to the mobile app: SimpleJWT tokens as PayRole issued them (access 8 hours,
refresh 30 days, rotated), with one more claim, `tid`, the client the token was issued on. The
app always talks to its client's own address, so a token is refused on any other client's host
(the claim is new; the app never reads it).

A request is the user's membership in the host's client, as on the screens: an inactive
membership, or a client where the user has none, is "User not found". The messages are
SimpleJWT's own English ones, which the app knows: they are not translated.
"""

from __future__ import annotations

from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.iam.authz import build_actor
from apps.iam.models import Membership, MembershipStatus

from . import devices

TENANT_CLAIM = "tid"
DEVICE_CLAIM = "did"  # the phone's record (apps/mobile/devices.py), when it named itself


def tokens_for(membership, device_pk: int | None = None) -> dict:
    refresh = RefreshToken.for_user(membership.user)
    refresh[TENANT_CLAIM] = membership.tenant_id
    if device_pk is not None:
        refresh[DEVICE_CLAIM] = device_pk
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def check_tenant(token, request) -> None:
    tenant = getattr(request, "tenant", None)
    if tenant is None or token.get(TENANT_CLAIM) != tenant.id:
        raise InvalidToken({"detail": "Given token not valid for any token type",
                            "messages": []})


def active_membership(user):
    return (Membership.objects.select_related("user", "default_branch")
            .filter(user=user, status=MembershipStatus.ACTIVE).first())


class AppTokenAuthentication(JWTAuthentication):
    """Bearer access token → the user, their membership here and its actor (for permissions
    and the audit trail)."""

    def authenticate(self, request):
        found = super().authenticate(request)
        if found is None:
            return None
        user, token = found
        check_tenant(token, request._request)
        membership = active_membership(user)
        if membership is None:
            raise AuthenticationFailed("User not found", code="user_not_found")
        device_pk = token.get(DEVICE_CLAIM)
        if device_pk is not None and not devices.is_allowed(device_pk):
            raise AuthenticationFailed("User not found", code="user_not_found")
        request._request.membership = membership
        request._request.actor = build_actor(membership)
        with connection.cursor() as cursor:  # who changed what (apps/audit)
            cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(user.pk)])
        return user, token

    def authenticate_header(self, request):
        return 'Bearer realm="api"'

