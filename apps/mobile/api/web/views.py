"""The browser's API for the mobile app: giving an employee their login (PUT) or taking it away
(DELETE) at /api/web/mobile/logins/<employee id>/; their QR at /qr/<employee id>/ (PUT a new one,
POST renew/, DELETE cancel); signing one phone out at DELETE /devices/<id>/."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ... import access, devices, qr
from .serializers import LoginWriteSerializer


class AppLoginViewSet(viewsets.GenericViewSet):
    required_permissions = {"update": access.USERS, "destroy": access.USERS}

    def update(self, request, pk=None):
        payload = LoginWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        member = access.give_login(int(pk), payload.validated_data["username"],
                                   payload.validated_data["password"], actor=request.actor)
        return Response({"id": member.pk, "username": member.username})

    def destroy(self, request, pk=None):
        access.take_login(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppQrViewSet(viewsets.GenericViewSet):
    required_permissions = {"update": qr.MANAGE, "renew": qr.MANAGE, "destroy": qr.MANAGE}

    def update(self, request, pk=None):
        issued = qr.issue(int(pk), actor=request.actor)
        text = qr.link_text(f"{request.scheme}://{request.get_host()}", issued.code)
        return Response({"svg": qr.qr_svg(text), "expires_at": issued.link.expires_at,
                         "username": issued.link.member.username})

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        return Response({"expires_at": qr.renew(int(pk), actor=request.actor).expires_at})

    def destroy(self, request, pk=None):
        qr.cancel(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppDeviceViewSet(viewsets.GenericViewSet):
    required_permissions = {"destroy": qr.MANAGE}

    def destroy(self, request, pk=None):
        devices.revoke(int(pk), actor=request.actor)
        return Response(status=status.HTTP_204_NO_CONTENT)
