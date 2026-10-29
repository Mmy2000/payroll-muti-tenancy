"""The browser's API for evaluations: POST one, PUT it, DELETE it."""

from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from . import services


class EvaluationWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    year = serializers.IntegerField()
    evaluated_on = serializers.DateField()
    note_1 = serializers.CharField(allow_blank=True, default="", max_length=5000)
    note_2 = serializers.CharField(allow_blank=True, default="", max_length=5000)
    note_3 = serializers.CharField(allow_blank=True, default="", max_length=5000)
    note_4 = serializers.CharField(allow_blank=True, default="", max_length=5000)


class EvaluationViewSet(viewsets.GenericViewSet):
    required_permissions = {"create": services.MANAGE, "update": services.MANAGE,
                            "destroy": services.MANAGE}

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


router = SimpleRouter()
router.register("evaluations", EvaluationViewSet, basename="evaluation")
urlpatterns = router.urls
