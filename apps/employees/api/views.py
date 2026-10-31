
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.employees.api.serializers import GroupFields
from apps.employees.api.targets import outcome_response
from apps.employees.models import Weekday

from .. import selectors
from ..permissions import MANAGE, SALARY_MANAGE, VIEW
from ..services import employees, group_hours
from .serializers import (
    CardWriteSerializer,
    EmployeeSerializer,
    LeaveSerializer,
    NewEmployeeSerializer,
    PayWriteSerializer,
    ReinstateSerializer,
    ScheduleWriteSerializer,
)


def _valid(serializer_class, data, prefix: str = ""):
    payload = serializer_class(data=data)
    if not payload.is_valid():
        errors = payload.errors if not prefix else {prefix: payload.errors}
        raise serializers.ValidationError(errors)
    return payload.validated_data


# --- views ---------------------------------------------------------------------------------


class EmployeeViewSet(viewsets.GenericViewSet):
    serializer_class = EmployeeSerializer
    filterset_fields = ["branch", "department"]
    required_permissions = {"list": VIEW, "retrieve": VIEW, "create": MANAGE, "update": MANAGE,
                            "pay": SALARY_MANAGE, "schedule": MANAGE, "leave": MANAGE,
                            "reinstate": MANAGE}

    def get_queryset(self):
        return selectors.listed_employees(self.request.actor)

    def _show(self, employee, code=status.HTTP_200_OK):
        from django.utils import timezone

        context = {**self.get_serializer_context(), "detail": True,
                   "today": timezone.localdate()}
        return Response(EmployeeSerializer(employee, context=context).data, status=code)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return self._show(self.get_object())

    def create(self, request):
        data = _valid(NewEmployeeSerializer, request.data)
        pay, schedule = data.pop("pay"), data.pop("schedule")
        employee = employees.create_employee(
            employees.EmployeeInput(**data), employees.CompensationInput(**pay),
            employees.ScheduleInput(**schedule), actor=request.actor)
        return self._show(employee, status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        data = _valid(CardWriteSerializer, request.data)
        employee = employees.update_employee(int(pk), employees.EmployeeInput(**data),
                                            actor=request.actor)
        return self._show(employee)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        data = _valid(PayWriteSerializer, request.data)
        employees.change_pay(int(pk), employees.CompensationInput(**data), actor=request.actor)
        return self._show(self.get_object())

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        data = _valid(ScheduleWriteSerializer, request.data)
        employees.change_schedule(int(pk), employees.ScheduleInput(**data), actor=request.actor)
        return self._show(self.get_object())

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        data = _valid(LeaveSerializer, request.data)
        employee = employees.end_employment(int(pk), data["left_on"], data["reason"],
                                           actor=request.actor)
        return self._show(employee)

    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        data = _valid(ReinstateSerializer, request.data)
        return self._show(employees.reinstate(int(pk), restore_login=data["restore_login"],
                                              actor=request.actor))


class PayChangeViewSet(viewsets.GenericViewSet):
    """DELETE a pay change entered by mistake."""

    required_permissions = {"destroy": SALARY_MANAGE}

    def destroy(self, request, pk=None):
        employees.delete_pay_change(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScheduleChangeViewSet(viewsets.GenericViewSet):
    """DELETE a change of hours entered by mistake."""

    required_permissions = {"destroy": MANAGE}

    def destroy(self, request, pk=None):
        employees.delete_schedule_change(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupHoursSerializer(GroupFields):
    effective_from = serializers.DateField()
    until = serializers.DateField(allow_null=True, required=False, default=None)
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()
    change_days_off = serializers.BooleanField(default=False)
    days_off = serializers.ListField(child=serializers.ChoiceField(choices=Weekday.choices),
                                     default=list, max_length=7)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class GroupHoursViewSet(viewsets.GenericViewSet):
    """POST new working hours for a group: previewed (`save` false), then saved."""

    required_permissions = {"create": MANAGE}

    def create(self, request):
        data = dict(_valid(GroupHoursSerializer, request.data))
        group, options = GroupFields.group(data), GroupFields.run_options(data)
        days_off = tuple(data.pop("days_off"))
        if not data.pop("change_days_off"):
            days_off = None  # each keeps their own
        outcome = group_hours.change_hours_for_group(
            group_hours.GroupHoursInput(group=group, days_off=days_off, **data), **options,
            actor=request.actor)
        return outcome_response(outcome)
