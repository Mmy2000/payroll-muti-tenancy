from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.core.api.fields import MonthField
from apps.employees.api.scoped import EmployeeRowsViewSet
from apps.loans import advances, services
from apps.loans.models import Advance, Loan, LoanInstallment


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


# --- advances ------------------------------------------------------------------------------


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


class AdvanceViewSet(EmployeeRowsViewSet):
    model = Advance
    view_permission = advances.VIEW
    serializer_class = AdvanceSerializer
    filterset_fields = ["status", "employee"]
    required_permissions = {"list": advances.VIEW, "create": advances.MANAGE,
                            "cancel": advances.MANAGE}

    def create(self, request):
        data = _valid(AdvanceWriteSerializer, request.data)
        advance = advances.give_advance(advances.AdvanceInput(**data), actor=request.actor)
        return Response(self.get_serializer(advance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self.get_serializer(
            advances.cancel_advance(int(pk), actor=request.actor)).data)


# --- loans ---------------------------------------------------------------------------------


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


class LoanViewSet(EmployeeRowsViewSet):
    model = Loan
    view_permission = services.VIEW
    serializer_class = LoanSerializer
    filterset_fields = ["status", "employee"]
    required_permissions = {"list": services.VIEW, "retrieve": services.VIEW,
                            "create": services.MANAGE, "cancel": services.MANAGE}

    def get_queryset(self):
        return super().get_queryset().prefetch_related("installments")

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        loan = services.grant_loan(services.LoanInput(**_valid(LoanWriteSerializer,
                                                               request.data)),
                                   actor=request.actor)
        return Response(self.get_serializer(loan).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self.get_serializer(services.cancel_loan(int(pk),
                                                                 actor=request.actor)).data)


class InstallmentViewSet(viewsets.GenericViewSet):
    """POST …/<id>/postpone/: this installment and every later due one a month on."""

    required_permissions = {"postpone": services.MANAGE}

    @action(detail=True, methods=["post"])
    def postpone(self, request, pk=None):
        loan = services.postpone_installment(int(pk), actor=request.actor)
        return Response(LoanSerializer(loan, context=self.get_serializer_context()).data)


router = SimpleRouter()
router.register("advances", AdvanceViewSet, basename="advance")
router.register("loans", LoanViewSet, basename="loan")
router.register("installments", InstallmentViewSet, basename="installment")
urlpatterns = router.urls
