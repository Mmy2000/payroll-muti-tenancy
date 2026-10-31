"""What the compensation API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from apps.compensation.models import PayItem, PayItemAssignment, PayItemBasis, PayItemKind


class PayItemSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    basis_label = serializers.CharField(source="get_basis_display", read_only=True)

    class Meta:
        model = PayItem
        fields = ["id", "code", "name", "kind", "kind_label", "basis", "basis_label", "taxable",
                  "is_active"]


class PayItemWriteSerializer(serializers.Serializer):
    code = serializers.IntegerField(min_value=1, max_value=99999)
    name = serializers.CharField(max_length=120)
    kind = serializers.ChoiceField(choices=PayItemKind.choices)
    basis = serializers.ChoiceField(choices=PayItemBasis.choices, default=PayItemBasis.FIXED)
    taxable = serializers.BooleanField(default=False)


class AssignmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)

    class Meta:
        model = PayItemAssignment
        fields = ["id", "employee", "employee_name", "item", "item_name", "frequency", "amount",
                  "starts_on", "ends_on", "note", "batch", "status"]


class CancelSerializer(serializers.Serializer):
    whole_batch = serializers.BooleanField(default=False)


class EndSerializer(serializers.Serializer):
    ends_on = serializers.DateField()
