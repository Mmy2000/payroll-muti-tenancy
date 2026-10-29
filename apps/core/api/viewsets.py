"""ViewSets for set-up data written through service functions (departments, pay items,
policies…). They hold no business rules: a subclass names its serializers and the service calls.

    class PayItemViewSet(ActivateMixin, ServiceViewSet):
        queryset = PayItem.objects.all()
        serializer_class = PayItemSerializer
        write_serializer_class = PayItemWriteSerializer
        required_permissions = {...}          # every action it serves

        def to_input(self, data):             # validated payload → the service's XInput
            return PayItemInput(**data)

        def save(self, data, pk, actor):      # create when pk is None
            return services.save_pay_item(data, item_id=pk, actor=actor)

        def set_active(self, pk, active, actor):   # ActivateMixin
            return services.set_pay_item_active(pk, active, actor=actor)

Only the mixins a ViewSet includes become routes: `ActivateMixin` (POST …/activate/ and
…/deactivate/) and `DestroyMixin` (DELETE, calling `destroy_object`).
"""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response


class ServiceViewSet(viewsets.GenericViewSet):
    """list, retrieve, create, update."""

    write_serializer_class = None

    def to_input(self, data: dict):
        raise NotImplementedError

    def save(self, data, pk: int | None, actor):
        raise NotImplementedError

    def _input(self):
        payload = self.write_serializer_class(data=self.request.data)
        payload.is_valid(raise_exception=True)
        return self.to_input(payload.validated_data)

    def _show(self, obj, code=status.HTTP_200_OK):
        return Response(self.get_serializer(obj).data, status=code)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return self._show(self.get_object())

    def create(self, request):
        return self._show(self.save(self._input(), None, request.actor), status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        self.get_object()  # 404 for a row the member can't see
        return self._show(self.save(self._input(), int(pk), request.actor))


class ActivateMixin:
    def set_active(self, pk: int, active: bool, actor):
        raise NotImplementedError

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        self.get_object()
        return self._show(self.set_active(int(pk), False, request.actor))

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        self.get_object()
        return self._show(self.set_active(int(pk), True, request.actor))


class DestroyMixin:
    def destroy_object(self, pk: int, actor) -> None:
        raise NotImplementedError

    def destroy(self, request, pk=None):
        self.get_object()
        self.destroy_object(int(pk), request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)
