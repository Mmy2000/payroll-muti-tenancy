from rest_framework import serializers
from rest_framework.routers import SimpleRouter

from apps.compensation import services
from apps.compensation.models import PayItem, PayItemBasis, PayItemKind
from apps.core.api.viewsets import ActivateMixin, ServiceViewSet


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


class PayItemViewSet(ActivateMixin, ServiceViewSet):
    queryset = PayItem.objects.all()
    serializer_class = PayItemSerializer
    write_serializer_class = PayItemWriteSerializer
    filterset_fields = ["is_active", "kind"]
    required_permissions = {
        "list": "compensation.item.view",
        "retrieve": "compensation.item.view",
        "create": "compensation.item.manage",
        "update": "compensation.item.manage",
        "deactivate": "compensation.item.manage",
        "activate": "compensation.item.manage",
    }

    def to_input(self, data):
        return services.PayItemInput(**data)

    def save(self, data, pk, actor):
        return services.save_pay_item(data, item_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return services.set_pay_item_active(pk, active, actor=actor)


router = SimpleRouter()
router.register("items", PayItemViewSet, basename="pay-item")
urlpatterns = router.urls
