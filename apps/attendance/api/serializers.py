"""What the attendance API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from apps.attendance.models import DayKind, HourlyLeave, LeaveRequest, LeaveType


class DayEntryWriteSerializer(serializers.Serializer):
    work_date = serializers.DateField()
    kind = serializers.ChoiceField(choices=DayKind.choices)
    check_in = serializers.TimeField(allow_null=True, required=False, default=None)
    check_out = serializers.TimeField(allow_null=True, required=False, default=None)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class OneDaySerializer(DayEntryWriteSerializer):
    employee_id = serializers.IntegerField()


class ManyDaysSerializer(DayEntryWriteSerializer):
    employee_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1,
                                         max_length=1000)
    shift_times = serializers.BooleanField(default=False)


class ClearDaySerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    work_date = serializers.DateField()


class OwnTimesSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    check_in = serializers.TimeField(allow_null=True, required=False, default=None)
    check_out = serializers.TimeField(allow_null=True, required=False, default=None)


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "code", "name", "paid", "uses_annual_balance", "is_active"]


class LeaveTypeWriteSerializer(serializers.Serializer):
    code = serializers.IntegerField(min_value=1, max_value=9999)
    name = serializers.CharField(max_length=120)
    paid = serializers.BooleanField(default=False)
    uses_annual_balance = serializers.BooleanField(default=False)


class DecisionSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class _RequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)


class LeaveRequestSerializer(_RequestSerializer):
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = ["id", "employee", "employee_name", "leave_type", "leave_type_name",
                  "start_date", "end_date", "days", "reason", "status", "status_label",
                  "decision_note", "decided_at"]


class LeaveRequestWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    leave_type_id = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    approve = serializers.BooleanField(default=False)


class HourlyLeaveSerializer(_RequestSerializer):
    class Meta:
        model = HourlyLeave
        fields = ["id", "employee", "employee_name", "work_date", "starts_at", "ends_at",
                  "minutes", "reason", "status", "status_label", "decision_note", "decided_at"]


class HourlyLeaveWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    work_date = serializers.DateField()
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    approve = serializers.BooleanField(default=False)


class SpanSerializer(serializers.Serializer):
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()
