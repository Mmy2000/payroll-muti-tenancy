from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.compensation import services
from apps.compensation.models import (
    ItemFrequency,
    PayItem,
    PayItemAssignment,
    PayItemBasis,
    PayItemKind,
)
from apps.core.api.viewsets import ActivateMixin, ServiceViewSet
from apps.employees.api.scoped import EmployeeRowsViewSet
from apps.employees.api.targets import TargetFields


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


class AssignmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)

    class Meta:
        model = PayItemAssignment
        fields = ["id", "employee", "employee_name", "item", "item_name", "frequency", "amount",
                  "starts_on", "ends_on", "note", "batch", "status"]


class AssignmentWriteSerializer(TargetFields):
    item_id = serializers.IntegerField()
    frequency = serializers.ChoiceField(choices=ItemFrequency.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(allow_null=True, required=False, default=None)
    note = serializers.CharField(max_length=300, allow_blank=True, default="")


class CancelSerializer(serializers.Serializer):
    whole_batch = serializers.BooleanField(default=False)


class EndSerializer(serializers.Serializer):
    ends_on = serializers.DateField()


class AssignmentViewSet(EmployeeRowsViewSet):
    model = PayItemAssignment
    view_permission = "compensation.entry.view"
    related = ("employee", "item")
    serializer_class = AssignmentSerializer
    filterset_fields = ["status", "employee", "item", "frequency"]
    required_permissions = {"list": "compensation.entry.view", "create": services.GIVE,
                            "cancel": services.GIVE, "end": services.GIVE}

    def create(self, request):
        payload = AssignmentWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        target = TargetFields.target(data)
        made = services.give_items(services.AssignmentInput(target=target, **data),
                                   actor=request.actor)
        return Response({"created": len(made)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        self.get_object()
        payload = CancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        count = services.cancel_assignment(
            int(pk), whole_batch=payload.validated_data["whole_batch"], actor=request.actor)
        return Response({"cancelled": count})

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        self.get_object()
        payload = EndSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = services.end_assignment(int(pk), payload.validated_data["ends_on"],
                                      actor=request.actor)
        return Response(self.get_serializer(row).data)


router = SimpleRouter()
router.register("items", PayItemViewSet, basename="pay-item")
router.register("assignments", AssignmentViewSet, basename="pay-item-assignment")
urlpatterns = router.urls
