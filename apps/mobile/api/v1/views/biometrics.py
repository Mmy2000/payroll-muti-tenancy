"""Linking the phone to the fingerprint."""

from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from .... import contract, selectors
from ....services import biometrics
from .. import serializers as s
from .base import AppView, valid


class EnrollView(AppView):
    def post(self, request):
        data = valid(s.EnrollSerializer, request.data)
        enrollment, secret = biometrics.enroll(self.employee(), data["device_id"],
                                             data["app_version"])
        return Response({"enrollment_id": enrollment.pk, "secret": secret,
                         "device_id": enrollment.device_id,
                         "enrolled_at": contract.moment(enrollment.enrolled_at)},
                        status=status.HTTP_201_CREATED)


class RevokeView(AppView):
    def post(self, request):
        biometrics.revoke(self.employee())
        return Response(status=status.HTTP_204_NO_CONTENT)


class BiometricStatusView(AppView):
    def get(self, request):
        enrollment = selectors.active_enrollment(self.employee())
        return Response({"enrolled": enrollment is not None,
                         "enrollment_id": enrollment.pk if enrollment else None,
                         "device_id": enrollment.device_id if enrollment else None,
                         "enrolled_at": contract.moment(enrollment.enrolled_at)
                         if enrollment else None})
