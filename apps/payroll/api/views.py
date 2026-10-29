from django.db.models import Count
from django.utils.translation import gettext as _
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.core.errors import NotFound
from apps.payroll import services
from apps.payroll.models import (
    Frequency,
    ManualLine,
    MonthlyRule,
    PayCalendar,
    PayrollRun,
    Payslip,
    PayslipLine,
    PeriodKind,
    ScopeKind,
)
from apps.payroll.selectors import issue_text, line_label, visible_runs


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


# --- calendars -----------------------------------------------------------------------------


class CalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayCalendar
        fields = ["frequency", "start_day", "anchor", "monthly_items"]


class CalendarWriteSerializer(serializers.Serializer):
    start_day = serializers.IntegerField(default=1)
    anchor = serializers.DateField(required=False, allow_null=True, default=None)
    monthly_items = serializers.ChoiceField(MonthlyRule.choices, default=MonthlyRule.SPLIT)


class CalendarViewSet(viewsets.GenericViewSet):
    """GET calendars/ and PUT calendars/<frequency>/."""

    serializer_class = CalendarSerializer
    lookup_field = "frequency"
    lookup_value_regex = "|".join(Frequency.values)
    required_permissions = {"list": services.READ, "update": services.SETUP}

    def list(self, request):
        calendars = [services.calendar_for(f) for f in Frequency.values]
        return Response(self.get_serializer(calendars, many=True).data)

    def update(self, request, frequency=None):
        data = _valid(CalendarWriteSerializer, request.data)
        calendar = services.save_calendar(services.CalendarInput(frequency=frequency, **data),
                                          actor=request.actor)
        return Response(self.get_serializer(calendar).data)


# --- runs ----------------------------------------------------------------------------------


class RunSerializer(serializers.ModelSerializer):
    frequency = serializers.CharField(source="period.frequency", read_only=True)
    kind = serializers.CharField(source="period.kind", read_only=True)
    start = serializers.DateField(source="period.start", read_only=True)
    end = serializers.DateField(source="period.end", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    payslip_count = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = ["id", "number", "frequency", "kind", "start", "end", "scope", "scope_id",
                  "status", "status_label", "note", "payslip_count", "skipped", "earnings",
                  "deductions", "net", "employer_cost", "calculated_at", "approved_at",
                  "paid_on", "payment_method", "payment_reference", "reversed_at",
                  "reversal_reason"]

    def get_payslip_count(self, run) -> int:
        counted = getattr(run, "payslip_count", None)  # annotated on lists
        return run.payslips.count() if counted is None else counted


class RunWriteSerializer(serializers.Serializer):
    frequency = serializers.ChoiceField(Frequency.choices)
    kind = serializers.ChoiceField(PeriodKind.choices, default=PeriodKind.REGULAR)
    day = serializers.DateField(required=False, allow_null=True, default=None)
    start = serializers.DateField(required=False, allow_null=True, default=None)
    end = serializers.DateField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    scope = serializers.ChoiceField(ScopeKind.choices, default=ScopeKind.ALL)
    scope_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class PaymentSerializer(serializers.Serializer):
    paid_on = serializers.DateField()
    method = serializers.CharField(max_length=40, allow_blank=True, default="")
    reference = serializers.CharField(max_length=120, allow_blank=True, default="")


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")


class ManualLineWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    label = serializers.CharField(max_length=200, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    addition = serializers.BooleanField(default=True)
    taxable = serializers.BooleanField(default=True)


class RunViewSet(viewsets.GenericViewSet):
    serializer_class = RunSerializer
    filterset_fields = ["status", "period__frequency", "period__kind"]
    required_permissions = {
        "list": services.READ, "retrieve": services.READ, "create": services.CALCULATE,
        "destroy": services.CALCULATE, "calculate": services.CALCULATE,
        "approve": services.APPROVE, "pay": services.PAY, "reverse": services.REVERSE,
        "lines": services.CALCULATE,
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


class LineSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()

    class Meta:
        model = PayslipLine
        fields = ["position", "code", "kind", "title", "label", "quantity", "rate", "amount",
                  "taxable", "source", "source_id"]

    def get_title(self, line) -> str:
        return line_label(line)


class PayslipSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    lines = LineSerializer(many=True, read_only=True)
    problems = serializers.SerializerMethodField()

    class Meta:
        model = Payslip
        fields = ["id", "run", "employee", "employee_name", "earnings", "deductions", "net",
                  "employer_cost", "blocking", "warnings", "issues", "problems", "lines",
                  "snapshot"]

    def get_problems(self, slip) -> list[str]:
        return [issue_text(issue) for issue in slip.issues]


class PayslipViewSet(viewsets.GenericViewSet):
    serializer_class = PayslipSerializer
    filterset_fields = ["run", "employee"]
    required_permissions = {"list": services.READ, "retrieve": services.READ}

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

    required_permissions = {"destroy": services.CALCULATE}

    def destroy(self, request, pk=None):
        if not ManualLine.objects.filter(pk=pk, run__in=visible_runs(request.actor)).exists():
            raise NotFound(_("Not found."))
        slip = services.remove_manual_line(int(pk), actor=request.actor)
        return Response(PayslipSerializer(slip).data)


router = SimpleRouter()
router.register("calendars", CalendarViewSet, basename="pay-calendar")
router.register("runs", RunViewSet, basename="payroll-run")
router.register("payslips", PayslipViewSet, basename="payslip")
router.register("manual-lines", ManualLineViewSet, basename="manual-line")
urlpatterns = router.urls
