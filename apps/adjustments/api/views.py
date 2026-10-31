"""Incentives and penalties: the same endpoints twice, once per kind, so each kind has its own
permissions (`adjustments.incentive.*`, `adjustments.penalty.*`).

    <kind>-types/          the kind's types
    <kind>-batches/        batches: give (POST), a draft's details (PUT), delete a draft,
                           and …/add/, …/approve/, …/reopen/, …/cancel/, …/correct/
    <kind>s/               the rows, one per employee: a draft row's quantity (PATCH), removing
                           a draft row (DELETE)
"""

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.adjustments.domain.amounts import CHOICES
from apps.adjustments.models import Adjustment, AdjustmentKind, AdjustmentType
from apps.adjustments.selectors import visible_batches
from apps.core.api.viewsets import ActivateMixin, ServiceViewSet
from apps.employees.api.scoped import EmployeeRowsViewSet
from apps.employees.api.serializers import TargetFields

from .. import permissions
from ..services import batches as batches_services
from ..services import types
from .serializers import (
    AddSerializer,
    AdjustmentSerializer,
    BatchSerializer,
    ChangeReasonSerializer,
    CorrectionSerializer,
    DetailsSerializer,
    ReasonSerializer,
    RowQuantitySerializer,
    TypeSerializer,
    TypeWriteSerializer,
)


def _permissions(kind: str, actions: dict) -> dict:
    return {name: permissions.permission(kind, level) for name, level in actions.items()}


class _TypeViewSet(ActivateMixin, ServiceViewSet):
    kind = ""
    serializer_class = TypeSerializer
    write_serializer_class = TypeWriteSerializer

    def get_queryset(self):
        return AdjustmentType.objects.filter(kind=self.kind)

    def to_input(self, data):
        return types.TypeInput(kind=self.kind, **data)

    def save(self, data, pk, actor):
        return types.save_type(data, type_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return types.set_type_active(pk, active, actor=actor)


TYPE_ACTIONS = {"list": "view", "retrieve": "view", "create": "manage", "update": "manage",
                "activate": "manage", "deactivate": "manage"}


class IncentiveTypeViewSet(_TypeViewSet):
    kind = AdjustmentKind.INCENTIVE
    required_permissions = _permissions(kind, TYPE_ACTIONS)


class PenaltyTypeViewSet(_TypeViewSet):
    kind = AdjustmentKind.PENALTY
    required_permissions = _permissions(kind, TYPE_ACTIONS)


# --- rows ----------------------------------------------------------------------------------


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


class _RowViewSet(EmployeeRowsViewSet):
    kind = ""
    model = Adjustment
    related = ("employee", "adjustment_type", "batch")
    serializer_class = AdjustmentSerializer
    filterset_fields = ["batch", "employee", "adjustment_type"]

    def rows(self):
        return Adjustment.objects.filter(kind=self.kind)

    def partial_update(self, request, pk=None):
        self.get_object()
        data = _valid(RowQuantitySerializer, request.data)
        row = batches_services.set_row_quantity(int(pk), data["quantity"],
                                        reason=data["change_reason"], actor=request.actor)
        return Response(self.get_serializer(row).data)

    def destroy(self, request, pk=None):
        self.get_object()
        data = _valid(ChangeReasonSerializer, request.data)
        batches_services.remove_row(int(pk), reason=data["change_reason"], actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


ROW_ACTIONS = {"list": "view", "partial_update": "manage", "destroy": "manage"}


class IncentiveViewSet(_RowViewSet):
    kind = AdjustmentKind.INCENTIVE
    view_permission = permissions.permission(kind, "view")
    required_permissions = _permissions(kind, ROW_ACTIONS)


class PenaltyViewSet(_RowViewSet):
    kind = AdjustmentKind.PENALTY
    view_permission = permissions.permission(kind, "view")
    required_permissions = _permissions(kind, ROW_ACTIONS)


# --- batches -------------------------------------------------------------------------------


class GiveSerializer(TargetFields):
    type_id = serializers.IntegerField()
    date = serializers.DateField()
    method = serializers.ChoiceField(choices=CHOICES)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    approve = serializers.BooleanField(default=False)


class _BatchViewSet(viewsets.GenericViewSet):
    kind = ""
    serializer_class = BatchSerializer

    def get_queryset(self):
        batches = visible_batches(self.request.actor, self.kind).select_related(
            "adjustment_type")
        state = self.request.query_params.get("status")
        return batches.filter(status=state) if state else batches

    def _show(self, batch, code=status.HTTP_200_OK):
        return Response(self.get_serializer(batch).data, status=code)

    def _visible(self, pk) -> int:
        self.get_object()  # 404 for a batch the member can't see
        return int(pk)

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset().order_by("-date", "-id"))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return self._show(self.get_object())

    def create(self, request):
        data = _valid(GiveSerializer, request.data)
        target, approve = TargetFields.target(data), data.pop("approve")
        if not AdjustmentType.objects.filter(pk=data["type_id"], kind=self.kind).exists():
            data["type_id"] = 0  # another kind's type: refused as unknown
        batch = batches_services.give(batches_services.AdjustmentInput(target=target, **data),
                                      approve=approve,
                                      actor=request.actor)
        return self._show(batch, status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        data = _valid(DetailsSerializer, request.data)
        reason = data.pop("change_reason")
        batch = batches_services.update_draft(self._visible(pk),
                                              batches_services.BatchInput(**data),
                                              reason=reason, actor=request.actor)
        return self._show(batch)

    def destroy(self, request, pk=None):
        batches_services.delete_draft(self._visible(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def add(self, request, pk=None):
        data = _valid(AddSerializer, request.data)
        batches_services.add_to_draft(self._visible(pk), TargetFields.target(data),
                              reason=data["change_reason"], actor=request.actor)
        return self._show(self.get_object())

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._show(batches_services.approve(self._visible(pk), actor=request.actor))

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        data = _valid(ReasonSerializer, request.data)
        return self._show(batches_services.reopen(self._visible(pk), data["reason"],
                                          actor=request.actor))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        data = _valid(ReasonSerializer, request.data)
        return self._show(batches_services.cancel(self._visible(pk), data["reason"],
                                          actor=request.actor))

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        data = _valid(CorrectionSerializer, request.data)
        quantities = {row["row_id"]: row["quantity"] for row in data["rows"]}
        fix = batches_services.correct(self._visible(pk), batches_services.CorrectionInput(
            date=data["date"], reason=data["reason"], quantities=quantities),
            approve=data["approve"], actor=request.actor)
        return self._show(fix, status.HTTP_201_CREATED)


BATCH_ACTIONS = {"list": "view", "retrieve": "view", "create": "manage", "update": "manage",
                 "destroy": "manage", "add": "manage", "approve": "approve",
                 "reopen": "approve", "cancel": "approve", "correct": "approve"}


class IncentiveBatchViewSet(_BatchViewSet):
    kind = AdjustmentKind.INCENTIVE
    required_permissions = _permissions(kind, BATCH_ACTIONS)


class PenaltyBatchViewSet(_BatchViewSet):
    kind = AdjustmentKind.PENALTY
    required_permissions = _permissions(kind, BATCH_ACTIONS)
