"""The mobile app's endpoints (`/api/v1/`, docs/mobile-api.md), answering as PayRole's did.

Every view runs in English, as PayRole's API did (DRF's and SimpleJWT's own messages are
English there); the business messages are the contract's Arabic ones. Errors are DRF's own
shape, not the web API's envelope.
"""

from __future__ import annotations

from django.utils import translation
from rest_framework import permissions
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler

from apps.employees.models import Employee

from .... import contract, selectors
from ....contract import AppError
from ..auth import AppTokenAuthentication

SIGNIN, MONITOR = "mobile.signin", "mobile.monitor.track"


def app_errors(exc, context):
    if isinstance(exc, AppError):
        return Response({"detail": exc.detail, "code": exc.code, **exc.extra},
                        status=exc.status)
    return exception_handler(exc, context)  # DRF's own shapes and messages


class EnglishMixin:
    renderer_classes = [JSONRenderer]

    def get_exception_handler(self):
        return app_errors

    def dispatch(self, request, *args, **kwargs):
        with translation.override("en"):
            return super().dispatch(request, *args, **kwargs)


class CanUseApp(permissions.BasePermission):
    def has_permission(self, request, view):
        actor = getattr(request._request, "actor", None)
        return bool(request.user and request.user.is_authenticated and actor is not None
                    and actor.can(SIGNIN))


class CanMonitor(CanUseApp):
    message = contract.MONITOR_ONLY

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request._request.actor.can(MONITOR)


class AppView(EnglishMixin, APIView):
    authentication_classes = [AppTokenAuthentication]
    permission_classes = [CanUseApp]

    @property
    def member(self):
        return self.request._request.membership

    def employee(self, *, status_code: int = 404) -> Employee:
        return selectors.employee_of(self.member, status=status_code)


def valid(serializer_class, data, **extra):
    payload = serializer_class(data=data, **extra)
    payload.is_valid(raise_exception=True)
    return payload.validated_data


# --- signing in ------------------------------------------------------------------------------


# --- the employee ----------------------------------------------------------------------------


# --- the fingerprint proof -------------------------------------------------------------------


# --- attendance ------------------------------------------------------------------------------


# --- leave -----------------------------------------------------------------------------------


# --- notifications ---------------------------------------------------------------------------


# --- tracking --------------------------------------------------------------------------------


# --- following routes --------------------------------------------------------------------------


