"""The company structure page's API: the tree, the people of one of its nodes, and the moves."""

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.org.permissions import DEPARTMENT_MANAGE

from .. import selectors
from ..permissions import MANAGE, VIEW
from ..services import structure
from .serializers import (
    AddDepartmentSerializer,
    MoveDepartmentSerializer,
    MovePeopleSerializer,
    RemoveDepartmentSerializer,
)


def _valid(serializer_class, data):
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return payload.validated_data


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


class StructureViewSet(viewsets.GenericViewSet):
    serializer_class = serializers.Serializer
    pagination_class = None
    required_permissions = {
        "list": VIEW, "people": VIEW, "search": VIEW, "move_people": MANAGE,
        "move_department": DEPARTMENT_MANAGE, "add_department": DEPARTMENT_MANAGE,
        "remove_department": DEPARTMENT_MANAGE,
    }

    def list(self, request):
        return Response(selectors.structure_tree(request.actor))

    @action(detail=False)
    def people(self, request):
        return Response(selectors.structure_people(
            request.actor, _int(request.query_params.get("branch")),
            _int(request.query_params.get("department"))))

    @action(detail=False)
    def search(self, request):
        return Response(selectors.structure_search(
            request.actor, request.query_params.get("q", "").strip()[:100]))

    @action(detail=False, methods=["post"], url_path="move-people")
    def move_people(self, request):
        data = _valid(MovePeopleSerializer, request.data)
        moved = structure.move_people(data["employee_ids"], data["branch_id"],
                                      data["department_id"], data["effective_from"],
                                      note=data["note"], actor=request.actor)
        return Response({"moved": moved})

    @action(detail=False, methods=["post"], url_path="move-department")
    def move_department(self, request):
        data = _valid(MoveDepartmentSerializer, request.data)
        moved = structure.move_department(data["department_id"], data["from_branch_id"],
                                          data["branch_id"], data["effective_from"],
                                          actor=request.actor)
        return Response({"moved": moved})

    @action(detail=False, methods=["post"], url_path="add-department")
    def add_department(self, request):
        data = _valid(AddDepartmentSerializer, request.data)
        structure.add_department(data["department_id"], data["branch_id"], actor=request.actor)
        return Response({"moved": 0})

    @action(detail=False, methods=["post"], url_path="remove-department")
    def remove_department(self, request):
        data = _valid(RemoveDepartmentSerializer, request.data)
        moved = structure.remove_department(data["department_id"], data["from_branch_id"],
                                            data["move_to"], data["effective_from"],
                                            actor=request.actor)
        return Response({"moved": moved})
