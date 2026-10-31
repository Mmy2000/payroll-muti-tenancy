"""The browser's API for fingerprint devices: setting them up, asking them things, linking PINs."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.devices.models import DeviceUser

from .. import permissions, selectors
from ..services import devices, links
from .serializers import AskSerializer, DeviceWriteSerializer, LinkSerializer


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


class DeviceViewSet(viewsets.GenericViewSet):
    """POST a device, PUT its settings; …/ask/ a command, …/resend/ every punch it holds,
    …/link-by-code/ the PINs that are employee codes."""

    required_permissions = {"create": permissions.MANAGE, "update": permissions.MANAGE,
                            "ask": permissions.MANAGE, "resend": permissions.MANAGE,
                            "link_by_code": permissions.MANAGE}

    def create(self, request):
        data = _valid(DeviceWriteSerializer, request.data)
        device = devices.save_device(devices.DeviceInput(**data), actor=request.actor)
        return Response({"id": device.pk}, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        data = _valid(DeviceWriteSerializer, request.data)
        device = devices.save_device(devices.DeviceInput(**data), device_id=int(pk),
                                      actor=request.actor)
        return Response({"id": device.pk})

    @action(detail=True, methods=["post"])
    def ask(self, request, pk=None):
        command = devices.ask(int(pk), devices.CommandInput(**_valid(AskSerializer,
                                                                        request.data)),
                               actor=request.actor)
        return Response({"id": command.pk, "status": command.status},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        devices.resend_all(int(pk), actor=request.actor)
        return Response({"id": int(pk)})

    @action(detail=True, methods=["post"], url_path="link-by-code")
    def link_by_code(self, request, pk=None):
        device = selectors.visible_devices(request.actor, permissions.MANAGE).filter(
            pk=pk).first()
        if device is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"linked": links.link_by_code(device.branch_id,
                                                         actor=request.actor)})


class DeviceUserViewSet(viewsets.GenericViewSet):
    """POST …/link/ {employee_id}: link a PIN (null unlinks)."""

    required_permissions = {"link": permissions.MANAGE}
    queryset = DeviceUser.objects.none()

    @action(detail=True, methods=["post"])
    def link(self, request, pk=None):
        data = _valid(LinkSerializer, request.data)
        user = links.link(int(pk), data["employee_id"], actor=request.actor)
        return Response({"id": user.pk, "employee_id": user.employee_id})
