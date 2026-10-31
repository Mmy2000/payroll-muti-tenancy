"""What the adjustments API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from apps.adjustments import services
from apps.adjustments.domain.amounts import CHOICES
from apps.adjustments.models import Adjustment, AdjustmentType
from apps.employees.api.serializers import TargetFields


class TypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdjustmentType
        fields = ["id", "kind", "code", "name", "is_active"]


class TypeWriteSerializer(serializers.Serializer):
    code = serializers.IntegerField(min_value=1, max_value=9999)
    name = serializers.CharField(max_length=120)


class AdjustmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    type_name = serializers.CharField(source="adjustment_type.name", read_only=True)
    status = serializers.CharField(source="batch.status", read_only=True)

    class Meta:
        model = Adjustment
        fields = ["id", "batch", "employee", "employee_name", "adjustment_type", "type_name",
                  "kind", "date", "method", "quantity", "amount", "reason", "corrects",
                  "status"]


class RowQuantitySerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    change_reason = serializers.CharField(max_length=300, allow_blank=True, default="")


class ChangeReasonSerializer(serializers.Serializer):
    change_reason = serializers.CharField(max_length=300, allow_blank=True, default="")


class BatchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    status = serializers.CharField()
    adjustment_type = serializers.IntegerField(source="adjustment_type_id")
    type_name = serializers.CharField(source="adjustment_type.name")
    date = serializers.DateField()
    method = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField()
    target_kind = serializers.CharField()
    target_id = serializers.IntegerField(allow_null=True)
    corrects = serializers.IntegerField(source="corrects_id", allow_null=True)
    revision = serializers.IntegerField()
    change_reason = serializers.CharField()
    approved_at = serializers.DateTimeField(allow_null=True)
    rows = serializers.SerializerMethodField()

    def get_rows(self, batch):
        paid = services.paid_rows(batch)
        now = services.effective_amounts(batch)
        return [{**AdjustmentSerializer(row).data, "paid": row.pk in paid,
                 "effective_amount": str(now[row.pk])}
                for row in batch.rows.select_related("employee", "adjustment_type", "batch")]


class DetailsSerializer(ChangeReasonSerializer):
    type_id = serializers.IntegerField()
    date = serializers.DateField()
    method = serializers.ChoiceField(choices=CHOICES)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")


class AddSerializer(TargetFields, ChangeReasonSerializer):
    pass


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")


class CorrectedRowSerializer(serializers.Serializer):
    row_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)


class CorrectionSerializer(serializers.Serializer):
    date = serializers.DateField()
    reason = serializers.CharField(max_length=300, allow_blank=True, default="")
    rows = CorrectedRowSerializer(many=True, min_length=1, max_length=2000)
    approve = serializers.BooleanField(default=False)
