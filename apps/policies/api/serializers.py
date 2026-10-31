"""What the policies API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from apps.policies.models import (
    InsuranceRate,
    LatenessPolicy,
    OvertimePolicy,
    PublicHoliday,
    TaxTable,
)


class BandWriteSerializer(serializers.Serializer):
    from_minutes = serializers.IntegerField(min_value=0, max_value=1440)
    to_minutes = serializers.IntegerField(min_value=0, max_value=1440)
    hours = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0)


class BandedPolicyWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    minutes = serializers.IntegerField(min_value=0, max_value=1440, default=0)
    bands = BandWriteSerializer(many=True, required=False, default=list)


class LatenessPolicySerializer(serializers.ModelSerializer):
    bands = serializers.SerializerMethodField()

    class Meta:
        model = LatenessPolicy
        fields = ["id", "name", "grace_minutes", "is_active", "bands"]

    def get_bands(self, policy):
        return [{"from_minutes": b.from_minutes, "to_minutes": b.to_minutes,
                 "hours": str(b.deduct_hours)} for b in policy.bands.all()]


class OvertimePolicySerializer(serializers.ModelSerializer):
    bands = serializers.SerializerMethodField()

    class Meta:
        model = OvertimePolicy
        fields = ["id", "name", "starts_after_minutes", "is_active", "bands"]

    def get_bands(self, policy):
        return [{"from_minutes": b.from_minutes, "to_minutes": b.to_minutes,
                 "hours": str(b.paid_hours)} for b in policy.bands.all()]


class BracketWriteSerializer(serializers.Serializer):
    up_to = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0,
                                     allow_null=True, required=False, default=None)
    rate = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0,
                                    max_value=100)


class TaxTableWriteSerializer(serializers.Serializer):
    effective_from = serializers.DateField()
    annual_exemption = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0,
                                                default=0)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")
    brackets = BracketWriteSerializer(many=True)


class TaxTableSerializer(serializers.ModelSerializer):
    brackets = serializers.SerializerMethodField()

    class Meta:
        model = TaxTable
        fields = ["id", "effective_from", "annual_exemption", "note", "brackets"]

    def get_brackets(self, table):
        return [{"up_to": None if b.up_to is None else str(b.up_to), "rate": str(b.rate)}
                for b in table.brackets.all()]


class InsuranceRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceRate
        fields = ["id", "effective_from", "employee_rate", "employer_rate", "min_insured",
                  "max_insured", "note"]


class InsuranceRateWriteSerializer(serializers.Serializer):
    effective_from = serializers.DateField()
    employee_rate = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0,
                                             max_value=100)
    employer_rate = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0,
                                             max_value=100)
    min_insured = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0,
                                           allow_null=True, required=False, default=None)
    max_insured = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0,
                                           allow_null=True, required=False, default=None)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class HolidaySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", default="", read_only=True)

    class Meta:
        model = PublicHoliday
        fields = ["id", "date", "name", "branch", "branch_name"]


class HolidayWriteSerializer(serializers.Serializer):
    date = serializers.DateField()
    name = serializers.CharField(max_length=120)
    branch_id = serializers.IntegerField(allow_null=True, required=False, default=None)
