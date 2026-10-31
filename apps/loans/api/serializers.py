"""What the loans API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from apps.core.api.fields import MonthField
from apps.loans import services
from apps.loans.models import Advance, Loan, LoanInstallment


class AdvanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Advance
        fields = ["id", "employee", "employee_name", "date", "amount", "reason", "status",
                  "status_label"]


class AdvanceWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")


class InstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanInstallment
        fields = ["id", "number", "due_month", "amount", "status"]


class LoanSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    installments = InstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = Loan
        fields = ["id", "employee", "employee_name", "granted_on", "amount", "reason", "status",
                  "status_label", "installments"]


class LoanWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    granted_on = serializers.DateField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    installments = serializers.IntegerField(min_value=1, max_value=services.MAX_INSTALLMENTS)
    first_month = MonthField()
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
