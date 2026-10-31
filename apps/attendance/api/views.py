from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.attendance.models import HourlyLeave, LeaveRequest, LeaveType
from apps.core.api.viewsets import ActivateMixin, ServiceViewSet
from apps.employees.api.scoped import EmployeeRowsViewSet
from apps.employees.api.serializers import GroupFields
from apps.employees.api.targets import outcome_response

from ..services import approvals, entries, hourly, leave
from .serializers import (
    ClearDaySerializer,
    DecisionSerializer,
    HourlyLeaveSerializer,
    HourlyLeaveWriteSerializer,
    LeaveRequestSerializer,
    LeaveRequestWriteSerializer,
    LeaveTypeSerializer,
    LeaveTypeWriteSerializer,
    ManyDaysSerializer,
    OneDaySerializer,
    OwnTimesSerializer,
    SpanSerializer,
)


class GroupTimesSerializer(GroupFields):
    work_date = serializers.DateField()
    check_in = serializers.TimeField(allow_null=True, required=False, default=None)
    check_out = serializers.TimeField(allow_null=True, required=False, default=None)
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    own_times = OwnTimesSerializer(many=True, required=False, default=list)
    replace = serializers.BooleanField(default=False)


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return payload.validated_data


def _entry(data: dict) -> entries.DayEntryInput:
    return entries.DayEntryInput(kind=data["kind"], check_in=data["check_in"],
                                 check_out=data["check_out"], note=data["note"],
                                 shift_times=data.get("shift_times", False))


class DayEntryViewSet(viewsets.GenericViewSet):
    """POST one day's entry, POST …/bulk/ the same entry for several employees, POST …/times/
    times entered by hand for a group (previewed, then saved), POST …/clear/ to remove an entry
    (the punches of the day count again)."""

    required_permissions = {"create": entries.MANAGE, "bulk": entries.MANAGE,
                            "times": entries.MANAGE, "clear": entries.MANAGE}

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
    def times(self, request):
        data = dict(_valid(GroupTimesSerializer, request.data))
        group, options = GroupFields.group(data), GroupFields.run_options(data)
        own = {row["employee_id"]: (row["check_in"], row["check_out"])
               for row in data.pop("own_times")}
        outcome = entries.set_times_for_group(
            entries.GroupTimesInput(group=group, own_times=own, **data), **options,
            actor=request.actor)
        return outcome_response(outcome)

    @action(detail=False, methods=["post"])
    def clear(self, request):
        data = _valid(ClearDaySerializer, request.data)
        entries.clear_day(data["employee_id"], data["work_date"], actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- leave types ---------------------------------------------------------------------------


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


class DecisionMixin:
    """POST …/approve/, …/reject/, …/cancel/ on a request (apps.attendance.services.approvals).
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


class GroupHourlyLeaveSerializer(GroupFields):
    work_date = serializers.DateField()
    spans = SpanSerializer(many=True, min_length=1, max_length=10)
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    approve = serializers.BooleanField(default=False)


class _RequestViewSet(DecisionMixin, EmployeeRowsViewSet):
    """list (the member's branches), create (optionally approved at once) and decisions."""

    write_serializer_class = None
    filterset_fields = ["status", "employee"]

    def record(self, data: dict, approve: bool):
        raise NotImplementedError

    def create(self, request):
        data = dict(_valid(self.write_serializer_class, request.data))
        approve = data.pop("approve")
        made = self.record(data, approve)
        return Response(self.get_serializer(made).data, status=status.HTTP_201_CREATED)


class LeaveRequestViewSet(_RequestViewSet):
    model = LeaveRequest
    related = ("employee", "leave_type")
    view_permission = "attendance.leave.view"
    serializer_class = LeaveRequestSerializer
    write_serializer_class = LeaveRequestWriteSerializer
    decision_service = staticmethod(leave.decide_leave)
    required_permissions = {"list": "attendance.leave.view", "create": leave.REQUEST,
                            "approve": leave.APPROVE, "reject": leave.APPROVE,
                            "cancel": leave.APPROVE}

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
                            "group": hourly.REQUEST, "approve": hourly.APPROVE,
                            "reject": hourly.APPROVE, "cancel": hourly.APPROVE}

    def record(self, data, approve):
        return hourly.record_hourly_leave(hourly.HourlyLeaveInput(**data), approve=approve,
                                          actor=self.request.actor)

    @action(detail=False, methods=["post"])
    def group(self, request):
        """The same spans for a group: previewed (`save` false), then saved."""
        data = dict(_valid(GroupHourlyLeaveSerializer, request.data))
        group, options = GroupFields.group(data), GroupFields.run_options(data)
        spans = tuple((span["starts_at"], span["ends_at"]) for span in data.pop("spans"))
        approve = data.pop("approve")
        outcome = hourly.record_hourly_leave_for_group(
            hourly.GroupHourlyLeaveInput(group=group, spans=spans, **data), approve=approve,
            **options, actor=request.actor)
        return outcome_response(outcome)
