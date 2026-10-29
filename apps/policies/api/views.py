from rest_framework import serializers
from rest_framework.routers import SimpleRouter

from apps.core.api.viewsets import ActivateMixin, DestroyMixin, ServiceViewSet
from apps.policies import services
from apps.policies.domain.bands import Band
from apps.policies.domain.tax import Bracket
from apps.policies.models import (
    InsuranceRate,
    LatenessPolicy,
    OvertimePolicy,
    PublicHoliday,
    TaxTable,
)

# --- lateness and overtime -----------------------------------------------------------------


class BandWriteSerializer(serializers.Serializer):
    from_minutes = serializers.IntegerField(min_value=0, max_value=1440)
    to_minutes = serializers.IntegerField(min_value=0, max_value=1440)
    hours = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0)


class BandedPolicyWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    minutes = serializers.IntegerField(min_value=0, max_value=1440, default=0)
    bands = BandWriteSerializer(many=True, required=False, default=list)


def _band_input(data):
    return services.BandedPolicyInput(name=data["name"], minutes=data["minutes"],
                                      bands=[Band(**b) for b in data["bands"]])


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


def _policy_permissions(area: str) -> dict:
    return {"list": f"policies.{area}.view", "retrieve": f"policies.{area}.view",
            "create": f"policies.{area}.manage", "update": f"policies.{area}.manage",
            "deactivate": f"policies.{area}.manage", "activate": f"policies.{area}.manage"}


class LatenessPolicyViewSet(ActivateMixin, ServiceViewSet):
    queryset = LatenessPolicy.objects.prefetch_related("bands")
    serializer_class = LatenessPolicySerializer
    write_serializer_class = BandedPolicyWriteSerializer
    required_permissions = _policy_permissions("lateness")

    def to_input(self, data):
        return _band_input(data)

    def save(self, data, pk, actor):
        return services.save_lateness_policy(data, policy_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return services.set_policy_active(LatenessPolicy, pk, active, actor=actor)


class OvertimePolicyViewSet(ActivateMixin, ServiceViewSet):
    queryset = OvertimePolicy.objects.prefetch_related("bands")
    serializer_class = OvertimePolicySerializer
    write_serializer_class = BandedPolicyWriteSerializer
    required_permissions = _policy_permissions("overtime")

    def to_input(self, data):
        return _band_input(data)

    def save(self, data, pk, actor):
        return services.save_overtime_policy(data, policy_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return services.set_policy_active(OvertimePolicy, pk, active, actor=actor)


# --- income tax ----------------------------------------------------------------------------


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


class TaxTableViewSet(DestroyMixin, ServiceViewSet):
    queryset = TaxTable.objects.prefetch_related("brackets")
    serializer_class = TaxTableSerializer
    write_serializer_class = TaxTableWriteSerializer
    required_permissions = {"list": "policies.tax.view", "retrieve": "policies.tax.view",
                            "create": "policies.tax.manage", "update": "policies.tax.manage",
                            "destroy": "policies.tax.manage"}

    def to_input(self, data):
        return services.TaxTableInput(
            effective_from=data["effective_from"], annual_exemption=data["annual_exemption"],
            note=data["note"], brackets=[Bracket(**b) for b in data["brackets"]])

    def save(self, data, pk, actor):
        return services.save_tax_table(data, table_id=pk, actor=actor)

    def destroy_object(self, pk, actor):
        services.delete_tax_table(pk, actor=actor)


# --- social insurance ----------------------------------------------------------------------


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


class InsuranceRateViewSet(DestroyMixin, ServiceViewSet):
    queryset = InsuranceRate.objects.all()
    serializer_class = InsuranceRateSerializer
    write_serializer_class = InsuranceRateWriteSerializer
    required_permissions = {
        "list": "policies.insurance.view", "retrieve": "policies.insurance.view",
        "create": "policies.insurance.manage", "update": "policies.insurance.manage",
        "destroy": "policies.insurance.manage"}

    def to_input(self, data):
        return services.InsuranceRateInput(**data)

    def save(self, data, pk, actor):
        return services.save_insurance_rate(data, rate_id=pk, actor=actor)

    def destroy_object(self, pk, actor):
        services.delete_insurance_rate(pk, actor=actor)


# --- public holidays -----------------------------------------------------------------------


class HolidaySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", default="", read_only=True)

    class Meta:
        model = PublicHoliday
        fields = ["id", "date", "name", "branch", "branch_name"]


class HolidayWriteSerializer(serializers.Serializer):
    date = serializers.DateField()
    name = serializers.CharField(max_length=120)
    branch_id = serializers.IntegerField(allow_null=True, required=False, default=None)


class HolidayViewSet(DestroyMixin, ServiceViewSet):
    queryset = PublicHoliday.objects.select_related("branch")
    serializer_class = HolidaySerializer
    write_serializer_class = HolidayWriteSerializer
    required_permissions = {
        "list": "policies.holiday.view", "retrieve": "policies.holiday.view",
        "create": "policies.holiday.manage", "update": "policies.holiday.manage",
        "destroy": "policies.holiday.manage"}

    def to_input(self, data):
        return services.HolidayInput(**data)

    def save(self, data, pk, actor):
        return services.save_holiday(data, holiday_id=pk, actor=actor)

    def destroy_object(self, pk, actor):
        services.delete_holiday(pk, actor=actor)


router = SimpleRouter()
router.register("lateness", LatenessPolicyViewSet, basename="lateness-policy")
router.register("overtime", OvertimePolicyViewSet, basename="overtime-policy")
router.register("tax-tables", TaxTableViewSet, basename="tax-table")
router.register("insurance-rates", InsuranceRateViewSet, basename="insurance-rate")
router.register("holidays", HolidayViewSet, basename="holiday")
urlpatterns = router.urls
