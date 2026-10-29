from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.attendance import approvals, entries, hourly, leave
from apps.attendance.models import DayKind, HourlyLeave, LeaveRequest, LeaveType
from apps.core.api.viewsets import ActivateMixin, ServiceViewSet
from apps.employees.services import visible_employees

# --- manual day entries --------------------------------------------------------------------


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


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return payload.validated_data


def _entry(data: dict) -> entries.DayEntryInput:
    return entries.DayEntryInput(kind=data["kind"], check_in=data["check_in"],
                                 check_out=data["check_out"], note=data["note"],
                                 shift_times=data.get("shift_times", False))


class DayEntryViewSet(viewsets.GenericViewSet):
    """POST one day's entry, POST …/bulk/ the same entry for several employees, POST …/clear/
    to remove an entry (the punches of the day count again)."""

    required_permissions = {"create": entries.MANAGE, "bulk": entries.MANAGE,
                            "clear": entries.MANAGE}

    def create(self, request):
        data = _valid(OneDaySerializer, request.data)
        entries.set_day(data["employee_id"], data["work_date"], _entry(data),
                        actor=request.actor)
        return Response({"saved": 1}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        data = _valid(ManyDaysSerializer, request.data)
        saved = entries.set_days(data["employee_ids"], data["work_date"], _entry(data),
                                 actor=request.actor)
        return Response({"saved": len(saved)})

    @action(detail=False, methods=["post"])
    def clear(self, request):
        data = _valid(ClearDaySerializer, request.data)
        entries.clear_day(data["employee_id"], data["work_date"], actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- leave types ---------------------------------------------------------------------------


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "code", "name", "paid", "uses_annual_balance", "is_active"]


class LeaveTypeWriteSerializer(serializers.Serializer):
    code = serializers.IntegerField(min_value=1, max_value=9999)
    name = serializers.CharField(max_length=120)
    paid = serializers.BooleanField(default=False)
    uses_annual_balance = serializers.BooleanField(default=False)


class LeaveTypeViewSet(ActivateMixin, ServiceViewSet):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    write_serializer_class = LeaveTypeWriteSerializer
    required_permissions = {"list": "attendance.leave.view", "retrieve": "attendance.leave.view",
                            "create": leave.MANAGE_TYPES, "update": leave.MANAGE_TYPES,
                            "activate": leave.MANAGE_TYPES, "deactivate": leave.MANAGE_TYPES}

    def to_input(self, data):
        return leave.LeaveTypeInput(**data)

    def save(self, data, pk, actor):
        return leave.save_leave_type(data, type_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return leave.set_leave_type_active(pk, active, actor=actor)


# --- requests: leave and hourly leave ------------------------------------------------------


class DecisionSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class DecisionMixin:
    """POST …/approve/, …/reject/, …/cancel/ on a request (apps.attendance.approvals).
    A subclass names `decision_service(request_id, move, note=…, actor=…)`."""

    decision_service = None

    def _decide(self, request, pk, move):
        note = _valid(DecisionSerializer, request.data)["note"]
        decided = type(self).decision_service(int(pk), move, note=note, actor=request.actor)
        return Response(self.get_serializer(decided).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, pk, approvals.APPROVE)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, pk, approvals.REJECT)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._decide(request, pk, approvals.CANCEL)


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


class _RequestViewSet(DecisionMixin, viewsets.GenericViewSet):
    """list (the member's branches), create (optionally approved at once) and decisions."""

    model = None
    view_permission = ""
    write_serializer_class = None
    filterset_fields = ["status", "employee"]

    def get_queryset(self):
        employees = visible_employees(self.request.actor, self.view_permission)
        return self.model.objects.filter(employee__in=employees).select_related("employee")

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def record(self, data: dict, approve: bool):
        raise NotImplementedError

    def create(self, request):
        data = dict(_valid(self.write_serializer_class, request.data))
        approve = data.pop("approve")
        made = self.record(data, approve)
        return Response(self.get_serializer(made).data, status=status.HTTP_201_CREATED)


class LeaveRequestViewSet(_RequestViewSet):
    model = LeaveRequest
    view_permission = "attendance.leave.view"
    serializer_class = LeaveRequestSerializer
    write_serializer_class = LeaveRequestWriteSerializer
    decision_service = staticmethod(leave.decide_leave)
    required_permissions = {"list": "attendance.leave.view", "create": leave.REQUEST,
                            "approve": leave.APPROVE, "reject": leave.APPROVE,
                            "cancel": leave.APPROVE}

    def get_queryset(self):
        return super().get_queryset().select_related("leave_type")

    def record(self, data, approve):
        return leave.request_leave(leave.LeaveRequestInput(**data), approve=approve,
                                   actor=self.request.actor)


class HourlyLeaveViewSet(_RequestViewSet):
    model = HourlyLeave
    view_permission = "attendance.hourly.view"
    serializer_class = HourlyLeaveSerializer
    write_serializer_class = HourlyLeaveWriteSerializer
    decision_service = staticmethod(hourly.decide_hourly_leave)
    required_permissions = {"list": "attendance.hourly.view", "create": hourly.REQUEST,
                            "approve": hourly.APPROVE, "reject": hourly.APPROVE,
                            "cancel": hourly.APPROVE}

    def record(self, data, approve):
        return hourly.record_hourly_leave(hourly.HourlyLeaveInput(**data), approve=approve,
                                          actor=self.request.actor)


router = SimpleRouter()
router.register("days", DayEntryViewSet, basename="attendance-day")
router.register("leave-types", LeaveTypeViewSet, basename="leave-type")
router.register("leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register("hourly-leave", HourlyLeaveViewSet, basename="hourly-leave")
urlpatterns = router.urls
