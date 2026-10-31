from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.api.viewsets import ActivateMixin, ServiceViewSet
from apps.org import services

from .. import selectors
from .serializers import (
    BranchSerializer,
    BranchWriteSerializer,
    DepartmentSerializer,
    DepartmentWriteSerializer,
    PositionSerializer,
    PositionWriteSerializer,
)


class BranchViewSet(viewsets.GenericViewSet):
    # Built at import time with no tenant context; bound to the request's tenant when DRF
    # clones it in get_queryset().
    queryset = selectors.all_branches()
    serializer_class = BranchSerializer
    filterset_fields = ["is_active", "is_head_office"]
    required_permissions = {
        "list": "org.branch.view",
        "retrieve": "org.branch.view",
        "create": "org.branch.manage",
        "update": "org.branch.manage",
        "deactivate": "org.branch.manage",
        "activate": "org.branch.manage",
    }

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def _input(self):
        payload = BranchWriteSerializer(data=self.request.data)
        payload.is_valid(raise_exception=True)
        return services.BranchInput(**payload.validated_data)

    def create(self, request):
        branch = services.create_branch(self._input(), actor=request.actor)
        return Response(self.get_serializer(branch).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        branch = services.update_branch(int(pk), self._input(), actor=request.actor)
        return Response(self.get_serializer(branch).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        branch = services.set_branch_active(int(pk), False, actor=request.actor)
        return Response(self.get_serializer(branch).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        branch = services.set_branch_active(int(pk), True, actor=request.actor)
        return Response(self.get_serializer(branch).data)


class DepartmentViewSet(ActivateMixin, ServiceViewSet):
    queryset = selectors.visible_departments()
    serializer_class = DepartmentSerializer
    write_serializer_class = DepartmentWriteSerializer
    filterset_fields = ["is_active"]
    required_permissions = {
        "list": "org.department.view",
        "retrieve": "org.department.view",
        "create": "org.department.manage",
        "update": "org.department.manage",
        "deactivate": "org.department.manage",
        "activate": "org.department.manage",
    }

    def get_queryset(self):
        departments = selectors.visible_departments(self.request.actor)
        branch = self.request.query_params.get("branch", "")
        return selectors.in_branches(departments, [branch]) if branch.isdigit() else departments

    def to_input(self, data):
        return services.DepartmentInput(branch_ids=tuple(data["branches"]), code=data["code"],
                                        name=data["name"])

    def save(self, data, pk, actor):
        return services.save_department(data, department_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return services.set_department_active(pk, active, actor=actor)


class PositionViewSet(ActivateMixin, ServiceViewSet):
    queryset = selectors.positions()
    serializer_class = PositionSerializer
    write_serializer_class = PositionWriteSerializer
    filterset_fields = ["is_active", "department"]
    required_permissions = {
        "list": "org.position.view",
        "retrieve": "org.position.view",
        "create": "org.position.manage",
        "update": "org.position.manage",
        "deactivate": "org.position.manage",
        "activate": "org.position.manage",
    }

    def to_input(self, data):
        return services.PositionInput(name=data["name"], department_id=data["department"])

    def save(self, data, pk, actor):
        return services.save_position(data, position_id=pk, actor=actor)

    def set_active(self, pk, active, actor):
        return services.set_position_active(pk, active, actor=actor)
