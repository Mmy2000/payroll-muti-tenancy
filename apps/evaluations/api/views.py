"""The browser's API for evaluations: POST one, PUT it, DELETE it."""

from rest_framework import status, viewsets
from rest_framework.response import Response

from .. import permissions, services
from .serializers import EvaluationWriteSerializer


class EvaluationViewSet(viewsets.GenericViewSet):
    required_permissions = {"create": permissions.MANAGE, "update": permissions.MANAGE,
                            "destroy": permissions.MANAGE}

    def _input(self):
        payload = EvaluationWriteSerializer(data=self.request.data)
        payload.is_valid(raise_exception=True)
        return services.EvaluationInput(**payload.validated_data)

    def create(self, request):
        row = services.save(self._input(), actor=request.actor)
        return Response({"id": row.pk, "number": row.number}, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        row = services.save(self._input(), evaluation_id=int(pk), actor=request.actor)
        return Response({"id": row.pk, "number": row.number})

    def destroy(self, request, pk=None):
        services.delete(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)
