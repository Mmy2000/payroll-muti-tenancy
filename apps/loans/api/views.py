from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.employees.api.scoped import EmployeeRowsViewSet
from apps.loans.models import Advance, Loan

from .. import permissions, selectors
from ..services import advances, loans
from .serializers import (
    AdvanceSerializer,
    AdvanceWriteSerializer,
    LoanSerializer,
    LoanWriteSerializer,
)


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


# --- advances ------------------------------------------------------------------------------


class AdvanceViewSet(EmployeeRowsViewSet):
    model = Advance
    view_permission = permissions.ADVANCE_VIEW
    serializer_class = AdvanceSerializer
    filterset_fields = ["status", "employee"]
    required_permissions = {"list": permissions.ADVANCE_VIEW,
                            "create": permissions.ADVANCE_MANAGE,
                            "cancel": permissions.ADVANCE_MANAGE}

    def create(self, request):
        data = _valid(AdvanceWriteSerializer, request.data)
        advance = advances.give_advance(advances.AdvanceInput(**data), actor=request.actor)
        return Response(self.get_serializer(advance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self.get_serializer(
            advances.cancel_advance(int(pk), actor=request.actor)).data)


# --- loans ---------------------------------------------------------------------------------


class LoanViewSet(EmployeeRowsViewSet):
    model = Loan
    view_permission = permissions.VIEW
    serializer_class = LoanSerializer
    filterset_fields = ["status", "employee"]
    required_permissions = {"list": permissions.VIEW, "retrieve": permissions.VIEW,
                            "create": permissions.MANAGE, "cancel": permissions.MANAGE}

    def rows(self):
        return selectors.loans_with_installments()

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        loan = loans.grant_loan(loans.LoanInput(**_valid(LoanWriteSerializer,
                                                               request.data)),
                                   actor=request.actor)
        return Response(self.get_serializer(loan).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self.get_serializer(loans.cancel_loan(int(pk),
                                                                 actor=request.actor)).data)


class InstallmentViewSet(viewsets.GenericViewSet):
    """POST …/<id>/postpone/: this installment and every later due one a month on."""

    required_permissions = {"postpone": permissions.MANAGE}

    @action(detail=True, methods=["post"])
    def postpone(self, request, pk=None):
        loan = loans.postpone_installment(int(pk), actor=request.actor)
        return Response(LoanSerializer(loan, context=self.get_serializer_context()).data)
