"""What the payroll API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from apps.payroll.models import (
    Frequency,
    MonthlyRule,
    PayCalendar,
    PayrollRun,
    Payslip,
    PayslipLine,
    PeriodKind,
    ScopeKind,
)
from apps.payroll.selectors import issue_text, line_label


class CalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayCalendar
        fields = ["frequency", "start_day", "anchor", "monthly_items"]


class CalendarWriteSerializer(serializers.Serializer):
    start_day = serializers.IntegerField(default=1)
    anchor = serializers.DateField(required=False, allow_null=True, default=None)
    monthly_items = serializers.ChoiceField(MonthlyRule.choices, default=MonthlyRule.SPLIT)


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
    scope_branch_id = serializers.IntegerField(required=False, allow_null=True, default=None)
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
