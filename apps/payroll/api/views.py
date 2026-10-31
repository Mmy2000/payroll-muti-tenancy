from django.utils.translation import gettext as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.errors import NotFound
from apps.payroll.models import Frequency

from .. import permissions, selectors
from ..services import calendars, lifecycle, manual_lines, runs
from .serializers import (
    CalendarSerializer,
    CalendarWriteSerializer,
    ManualLineWriteSerializer,
    PaymentSerializer,
    PayslipSerializer,
    ReasonSerializer,
    RunSerializer,
    RunWriteSerializer,
)


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


# --- calendars -----------------------------------------------------------------------------


class CalendarViewSet(viewsets.GenericViewSet):
    """GET calendars/ and PUT calendars/<frequency>/."""

    serializer_class = CalendarSerializer
    lookup_field = "frequency"
    lookup_value_regex = "|".join(Frequency.values)
    required_permissions = {"list": permissions.READ, "update": permissions.SETUP}

    def list(self, request):
        rows = [calendars.calendar_for(f) for f in Frequency.values]
        return Response(self.get_serializer(rows, many=True).data)

    def update(self, request, frequency=None):
        data = _valid(CalendarWriteSerializer, request.data)
        calendar = calendars.save_calendar(calendars.CalendarInput(frequency=frequency, **data),
                                           actor=request.actor)
        return Response(self.get_serializer(calendar).data)


# --- runs ----------------------------------------------------------------------------------


class RunViewSet(viewsets.GenericViewSet):
    serializer_class = RunSerializer
    filterset_fields = ["status", "period__frequency", "period__kind"]
    required_permissions = {
        "list": permissions.READ, "retrieve": permissions.READ, "create": permissions.CALCULATE,
        "destroy": permissions.CALCULATE, "calculate": permissions.CALCULATE,
        "approve": permissions.APPROVE, "pay": permissions.PAY, "reverse": permissions.REVERSE,
        "lines": permissions.CALCULATE,
    }

    def get_queryset(self):
        return selectors.runs_with_counts(self.request.actor)

    def _show(self, run, code=status.HTTP_200_OK):
        return Response(self.get_serializer(run).data, status=code)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return self._show(self.get_object())

    def create(self, request):
        data = _valid(RunWriteSerializer, request.data)
        return self._show(runs.create_run(runs.RunInput(**data), actor=request.actor),
                          status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        self.get_object()
        runs.delete_draft(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def calculate(self, request, pk=None):
        self.get_object()
        return self._show(runs.calculate_run(int(pk), actor=request.actor))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        self.get_object()
        return self._show(lifecycle.approve_run(int(pk), actor=request.actor))

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        self.get_object()
        data = _valid(PaymentSerializer, request.data)
        return self._show(lifecycle.record_payment(int(pk), lifecycle.PaymentInput(**data),
                                                  actor=request.actor))

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        self.get_object()
        data = _valid(ReasonSerializer, request.data)
        return self._show(lifecycle.reverse_run(int(pk), data["reason"], actor=request.actor))

    @action(detail=True, methods=["post"])
    def lines(self, request, pk=None):
        """Add a manual line to an employee's payslip in this draft."""
        self.get_object()
        data = _valid(ManualLineWriteSerializer, request.data)
        slip = manual_lines.add_manual_line(int(pk), manual_lines.ManualLineInput(**data),
                                        actor=request.actor)
        return Response(PayslipSerializer(slip).data, status=status.HTTP_201_CREATED)


# --- payslips ------------------------------------------------------------------------------


class PayslipViewSet(viewsets.GenericViewSet):
    serializer_class = PayslipSerializer
    filterset_fields = ["run", "employee"]
    required_permissions = {"list": permissions.READ, "retrieve": permissions.READ}

    def get_queryset(self):
        return selectors.visible_payslips(self.request.actor)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)


class ManualLineViewSet(viewsets.GenericViewSet):
    """DELETE manual-lines/<id>/: remove a line a manager added to a draft."""

    required_permissions = {"destroy": permissions.CALCULATE}

    def destroy(self, request, pk=None):
        if not selectors.manual_line_visible(request.actor, pk):
            raise NotFound(_("Not found."))
        slip = manual_lines.remove_manual_line(int(pk), actor=request.actor)
        return Response(PayslipSerializer(slip).data)
