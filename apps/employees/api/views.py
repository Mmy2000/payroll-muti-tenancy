
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.employees import group_hours, services
from apps.employees.api.serializers import GroupFields
from apps.employees.api.targets import outcome_response
from apps.employees.models import Weekday
from apps.employees.services import MANAGE, SALARY_MANAGE, VIEW

from .serializers import (
    CardWriteSerializer,
    EmployeeSerializer,
    LeaveSerializer,
    NewEmployeeSerializer,
    PayWriteSerializer,
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
        return services.visible_employees(self.request.actor).select_related(
            "branch", "department")

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
        employee = services.create_employee(
            services.EmployeeInput(**data), services.CompensationInput(**pay),
            services.ScheduleInput(**schedule), actor=request.actor)
        return self._show(employee, status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        data = _valid(CardWriteSerializer, request.data)
        employee = services.update_employee(int(pk), services.EmployeeInput(**data),
                                            actor=request.actor)
        return self._show(employee)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        data = _valid(PayWriteSerializer, request.data)
        services.change_pay(int(pk), services.CompensationInput(**data), actor=request.actor)
        return self._show(self.get_object())

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        data = _valid(ScheduleWriteSerializer, request.data)
        services.change_schedule(int(pk), services.ScheduleInput(**data), actor=request.actor)
        return self._show(self.get_object())

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        data = _valid(LeaveSerializer, request.data)
        employee = services.end_employment(int(pk), data["left_on"], data["reason"],
                                           actor=request.actor)
        return self._show(employee)

    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        return self._show(services.reinstate(int(pk), actor=request.actor))


class PayChangeViewSet(viewsets.GenericViewSet):
    """DELETE a pay change entered by mistake."""

    required_permissions = {"destroy": SALARY_MANAGE}

    def destroy(self, request, pk=None):
        services.delete_pay_change(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScheduleChangeViewSet(viewsets.GenericViewSet):
    """DELETE a change of hours entered by mistake."""

    required_permissions = {"destroy": MANAGE}

    def destroy(self, request, pk=None):
        services.delete_schedule_change(int(pk), actor=request.actor)
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


router = SimpleRouter()
router.register("employees", EmployeeViewSet, basename="employee")
router.register("pay-changes", PayChangeViewSet, basename="pay-change")
router.register("schedule-changes", ScheduleChangeViewSet, basename="schedule-change")
router.register("group-hours", GroupHoursViewSet, basename="group-hours")
urlpatterns = router.urls
