from django.db.models import Count
from django.utils.translation import gettext as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.errors import NotFound
from apps.payroll import services
from apps.payroll.models import (
    Frequency,
    ManualLine,
    Payslip,
)
from apps.payroll.selectors import visible_runs

from .. import permissions
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
        calendars = [services.calendar_for(f) for f in Frequency.values]
        return Response(self.get_serializer(calendars, many=True).data)

    def update(self, request, frequency=None):
        data = _valid(CalendarWriteSerializer, request.data)
        calendar = services.save_calendar(services.CalendarInput(frequency=frequency, **data),
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
        return (visible_runs(self.request.actor).annotate(payslip_count=Count("payslips"))
                .order_by("-period__start", "-id"))

    def _show(self, run, code=status.HTTP_200_OK):
        return Response(self.get_serializer(run).data, status=code)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return self._show(self.get_object())

    def create(self, request):
        data = _valid(RunWriteSerializer, request.data)
        return self._show(services.create_run(services.RunInput(**data), actor=request.actor),
                          status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        self.get_object()
        services.delete_draft(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def calculate(self, request, pk=None):
        self.get_object()
        return self._show(services.calculate_run(int(pk), actor=request.actor))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        self.get_object()
        return self._show(services.approve_run(int(pk), actor=request.actor))

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        self.get_object()
        data = _valid(PaymentSerializer, request.data)
        return self._show(services.record_payment(int(pk), services.PaymentInput(**data),
                                                  actor=request.actor))

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        self.get_object()
        data = _valid(ReasonSerializer, request.data)
        return self._show(services.reverse_run(int(pk), data["reason"], actor=request.actor))

    @action(detail=True, methods=["post"])
    def lines(self, request, pk=None):
        """Add a manual line to an employee's payslip in this draft."""
        self.get_object()
        data = _valid(ManualLineWriteSerializer, request.data)
        slip = services.add_manual_line(int(pk), services.ManualLineInput(**data),
                                        actor=request.actor)
        return Response(PayslipSerializer(slip).data, status=status.HTTP_201_CREATED)


# --- payslips ------------------------------------------------------------------------------


class PayslipViewSet(viewsets.GenericViewSet):
    serializer_class = PayslipSerializer
    filterset_fields = ["run", "employee"]
    required_permissions = {"list": permissions.READ, "retrieve": permissions.READ}

    def get_queryset(self):
        return (Payslip.objects.filter(run__in=visible_runs(self.request.actor))
                .select_related("employee").prefetch_related("lines"))

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)


class ManualLineViewSet(viewsets.GenericViewSet):
    """DELETE manual-lines/<id>/: remove a line a manager added to a draft."""

    required_permissions = {"destroy": permissions.CALCULATE}

    def destroy(self, request, pk=None):
        if not ManualLine.objects.filter(pk=pk, run__in=visible_runs(request.actor)).exists():
            raise NotFound(_("Not found."))
        slip = services.remove_manual_line(int(pk), actor=request.actor)
        return Response(PayslipSerializer(slip).data)
