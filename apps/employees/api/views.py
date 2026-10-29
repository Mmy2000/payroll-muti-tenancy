from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.core.history import in_effect
from apps.employees import group_hours, services
from apps.employees.api.targets import GroupFields, outcome_response
from apps.employees.models import (
    Compensation,
    Employee,
    Gender,
    MaritalStatus,
    MilitaryStatus,
    PayFrequency,
    WageType,
    Weekday,
    WorkSchedule,
)
from apps.employees.services import MANAGE, SALARY_MANAGE, SALARY_READ, VIEW

# --- reading -------------------------------------------------------------------------------


class CompensationSerializer(serializers.ModelSerializer):
    daily_rate = serializers.SerializerMethodField()
    hourly_rate = serializers.SerializerMethodField()

    class Meta:
        model = Compensation
        fields = ["id", "effective_from", "wage_type", "pay_frequency", "salary",
                  "hours_per_day",
                  "overtime_multiplier", "absence_multiplier", "holiday_multiplier",
                  "insured_salary", "annual_leave_days", "permission_hours", "note",
                  "daily_rate", "hourly_rate"]

    def get_daily_rate(self, row):
        return str(row.terms.daily)

    def get_hourly_rate(self, row):
        return str(row.terms.hourly)


class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkSchedule
        fields = ["id", "effective_from", "starts_at", "ends_at", "days_off", "lateness_policy",
                  "overtime_policy", "early_leave_minutes", "note"]


class EmployeeSerializer(serializers.ModelSerializer):
    """The card. The national ID only for members who manage employees; pay only for members
    who may see it (`employees.salary.read`)."""

    branch_name = serializers.CharField(source="branch.name", read_only=True)
    department_name = serializers.CharField(source="department.name", default="",
                                            read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Employee
        fields = ["id", "code", "name", "branch", "branch_name", "department", "department_name",
                  "job_title", "hired_on", "left_on", "leave_reason", "is_active", "gender",
                  "birth_date", "phone", "email", "address", "insurance_number", "insured_from",
                  "qualification", "marital_status", "children", "military_status", "notes"]

    def to_representation(self, employee):
        data = super().to_representation(employee)
        actor = self.context["request"].actor
        if actor.can(MANAGE, branch=employee.branch_id):
            data["national_id"] = employee.national_id
        if self.context.get("detail"):
            today = self.context["today"]
            schedule = in_effect(employee.schedules.all(), today)
            data["schedule"] = ScheduleSerializer(schedule).data if schedule else None
            if actor.can(SALARY_READ, branch=employee.branch_id):
                pay = in_effect(employee.pay_history.all(), today)
                data["pay"] = CompensationSerializer(pay).data if pay else None
        return data


# --- writing -------------------------------------------------------------------------------


def _choice(choices):
    return serializers.ChoiceField(choices=choices, allow_blank=True, default="")


class CardWriteSerializer(serializers.Serializer):
    code = serializers.IntegerField(min_value=1, max_value=999999)
    name = serializers.CharField(max_length=200)
    branch_id = serializers.IntegerField()
    department_id = serializers.IntegerField(allow_null=True, required=False, default=None)
    hired_on = serializers.DateField()
    job_title = serializers.CharField(max_length=120, allow_blank=True, default="")
    gender = _choice(Gender.choices)
    national_id = serializers.CharField(max_length=30, allow_blank=True, default="")
    birth_date = serializers.DateField(allow_null=True, required=False, default=None)
    phone = serializers.CharField(max_length=30, allow_blank=True, default="")
    email = serializers.EmailField(allow_blank=True, default="")
    address = serializers.CharField(allow_blank=True, default="")
    insurance_number = serializers.CharField(max_length=30, allow_blank=True, default="")
    insured_from = serializers.DateField(allow_null=True, required=False, default=None)
    qualification = serializers.CharField(max_length=200, allow_blank=True, default="")
    marital_status = _choice(MaritalStatus.choices)
    children = serializers.IntegerField(min_value=0, max_value=50, default=0)
    military_status = _choice(MilitaryStatus.choices)
    notes = serializers.CharField(allow_blank=True, default="")


def _decimal(digits, places, **extra):
    return serializers.DecimalField(max_digits=digits, decimal_places=places, **extra)


class PayWriteSerializer(serializers.Serializer):
    effective_from = serializers.DateField(allow_null=True, required=False, default=None)
    wage_type = serializers.ChoiceField(choices=WageType.choices, default=WageType.FIXED)
    pay_frequency = serializers.ChoiceField(choices=PayFrequency.choices,
                                            default=PayFrequency.MONTHLY)
    salary = _decimal(12, 2, min_value=0)
    hours_per_day = _decimal(4, 2, default=Decimal("8"))
    overtime_multiplier = _decimal(5, 2, min_value=0, default=Decimal("1.5"))
    absence_multiplier = _decimal(5, 2, min_value=0, default=Decimal("1"))
    holiday_multiplier = _decimal(5, 2, min_value=0, default=Decimal("1"))
    insured_salary = _decimal(12, 2, min_value=0, allow_null=True, required=False, default=None)
    annual_leave_days = serializers.IntegerField(min_value=0, max_value=366, default=21)
    permission_hours = _decimal(5, 2, min_value=0, default=Decimal("0"))
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class ScheduleWriteSerializer(serializers.Serializer):
    effective_from = serializers.DateField(allow_null=True, required=False, default=None)
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()
    days_off = serializers.ListField(child=serializers.ChoiceField(choices=Weekday.choices),
                                     default=list, max_length=7)
    lateness_policy_id = serializers.IntegerField(allow_null=True, required=False, default=None)
    overtime_policy_id = serializers.IntegerField(allow_null=True, required=False, default=None)
    early_leave_minutes = serializers.IntegerField(min_value=0, max_value=600, default=0)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class NewEmployeeSerializer(CardWriteSerializer):
    pay = PayWriteSerializer()
    schedule = ScheduleWriteSerializer()


class LeaveSerializer(serializers.Serializer):
    left_on = serializers.DateField()
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")


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
