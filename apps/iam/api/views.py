from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errors import ValidationError
from apps.iam import selectors, services
from apps.iam.catalog import AUTHENTICATED, WILDCARD, permissions
from apps.iam.models import MembershipStatus

from .serializers import (
    MemberReadSerializer,
    MemberWriteSerializer,
    MeSerializer,
    PasswordSerializer,
    RoleReadSerializer,
    RoleWriteSerializer,
    ShortcutSerializer,
)


class MeView(APIView):
    """The signed-in member of the current tenant, with their effective permissions, so the UI
    can show only the actions they may take (the server still checks every request)."""

    serializer_class = MeSerializer
    required_permissions = {"GET": AUTHENTICATED}

    def get(self, request):
        actor = request.actor
        granted = sorted(permissions()) if WILDCARD in actor.grants else sorted(actor.grants)
        data = MeSerializer(request.membership).data
        data["permissions"] = granted
        return Response(data)


def _link_employee(membership, data, actor) -> None:
    """The user form also says which employee the user is: saved with the user, in the same
    transaction. The rules are the mobile app's (apps.mobile.services.access), imported here
    only."""
    if "employee" in data:
        from apps.mobile.services.access import link_member

        link_member(membership.pk, data["employee"], actor=actor)


def _member_input(data) -> services.MemberInput:
    return services.MemberInput(
        username=data["username"],
        display_name=data["display_name"],
        email=data["email"],
        phone=data["phone"],
        default_branch_id=data["default_branch"],
        roles=tuple(
            services.RoleAssignmentInput(
                role_id=r["role"],
                branch_ids=None if r["all_branches"] else tuple(r["branches"]),
            )
            for r in data["roles"]
        ),
    )


class MemberViewSet(viewsets.GenericViewSet):
    queryset = selectors.members_with_roles()
    serializer_class = MemberReadSerializer
    required_permissions = {
        "list": "admin.users.view",
        "retrieve": "admin.users.view",
        "create": "admin.users.manage",
        "update": "admin.users.manage",
        "suspend": "admin.users.manage",
        "activate": "admin.users.manage",
        "set_password": "admin.users.manage",
    }

    def _respond(self, membership, code=status.HTTP_200_OK):
        return Response(self.get_serializer(selectors.member_with_roles(membership.pk)).data,
                        status=code)

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        payload = MemberWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        if not payload.validated_data.get("password"):
            raise ValidationError(_("Please correct the highlighted fields."),
                                  fields={"password": [_("This field is required.")]})
        with transaction.atomic():
            membership = services.create_member(_member_input(payload.validated_data),
                                                payload.validated_data["password"],
                                                actor=request.actor)
            _link_employee(membership, payload.validated_data, request.actor)
        return self._respond(membership, status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        payload = MemberWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            membership = services.update_member(int(pk), _member_input(payload.validated_data),
                                                actor=request.actor)
            _link_employee(membership, payload.validated_data, request.actor)
        return self._respond(membership)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        membership = services.set_member_status(int(pk), MembershipStatus.SUSPENDED,
                                                actor=request.actor)
        return self._respond(membership)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        membership = services.set_member_status(int(pk), MembershipStatus.ACTIVE,
                                                actor=request.actor)
        return self._respond(membership)

    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        payload = PasswordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.set_member_password(int(pk), payload.validated_data["password"],
                                     actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleViewSet(viewsets.GenericViewSet):
    queryset = selectors.roles_with_member_counts()
    serializer_class = RoleReadSerializer
    required_permissions = {
        "list": "admin.users.view",
        "retrieve": "admin.users.view",
        "create": "admin.roles.manage",
        "update": "admin.roles.manage",
        "destroy": "admin.roles.manage",
    }

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        payload = RoleWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        role = services.create_role(data["name"], data["description"], data["permissions"],
                                    actor=request.actor)
        return Response(self.get_serializer(selectors.role_with_member_count(role.pk)).data,
                        status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        payload = RoleWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        role = services.update_role(int(pk), data["name"], data["description"],
                                    data["permissions"], actor=request.actor)
        return Response(self.get_serializer(selectors.role_with_member_count(role.pk)).data)

    def destroy(self, request, pk=None):
        services.delete_role(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShortcutsView(APIView):
    """The member's pinned screens; POST {screen, pinned} pins or unpins one."""

    required_permissions = {"GET": AUTHENTICATED, "POST": AUTHENTICATED}

    def get(self, request):
        from apps.iam import shortcuts

        return Response({"results": shortcuts.pinned(request.actor)})

    def post(self, request):
        from apps.iam import shortcuts

        serializer = ShortcutSerializer(data=request.data)
        if not serializer.is_valid():
            raise ValidationError(_("Please correct the highlighted fields."),
                                  fields=serializer.errors)
        data = serializer.validated_data
        if data["pinned"]:
            shortcuts.pin(request.actor, data["screen"])
        else:
            shortcuts.unpin(request.actor, data["screen"])
        return Response({"pinned": data["pinned"],
                         "results": shortcuts.pinned(request.actor)})
