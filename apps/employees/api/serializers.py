"""What the employees API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.core.history import in_effect
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
from apps.employees.targets import GROUP_KINDS, KINDS, Group, Target

from ..permissions import MANAGE, SALARY_READ


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


class TargetFields(serializers.Serializer):
    """Mix into a write serializer: `target_kind` (employee / department / branch) and
    `target_id`; `target(data)` gives the Target."""

    target_kind = serializers.ChoiceField(choices=[(k, k) for k in KINDS])
    target_id = serializers.IntegerField()

    @staticmethod
    def target(data: dict) -> Target:
        return Target(data.pop("target_kind"), data.pop("target_id"))


class GroupFields(serializers.Serializer):
    """Mix into the write serializer of a bulk change (apps/core/bulk.py): who (`group_kind`:
    employees / department / branch, with `employee_ids` or `group_id`), and whether to only
    preview (`save` false), or to save, leaving out rows that fail (`skip_failed`)."""

    group_kind = serializers.ChoiceField(choices=[(k, k) for k in GROUP_KINDS])
    employee_ids = serializers.ListField(child=serializers.IntegerField(), required=False,
                                         default=list, max_length=2000)
    group_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    save = serializers.BooleanField(default=False)
    skip_failed = serializers.BooleanField(default=False)

    @staticmethod
    def group(data: dict) -> Group:
        return Group(data.pop("group_kind"), tuple(data.pop("employee_ids")),
                     data.pop("group_id"))

    @staticmethod
    def run_options(data: dict) -> dict:
        return {"save": data.pop("save"), "skip_failed": data.pop("skip_failed")}
