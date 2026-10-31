
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

from .serializers import (
    BandedPolicyWriteSerializer,
    HolidaySerializer,
    HolidayWriteSerializer,
    InsuranceRateSerializer,
    InsuranceRateWriteSerializer,
    LatenessPolicySerializer,
    OvertimePolicySerializer,
    TaxTableSerializer,
    TaxTableWriteSerializer,
)


def _band_input(data):
    return services.BandedPolicyInput(name=data["name"], minutes=data["minutes"],
                                      bands=[Band(**b) for b in data["bands"]])


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
