"""The browser's API for the mobile app: giving an employee their login (PUT) or taking it
away (DELETE), at /api/web/mobile/logins/<employee id>/."""

from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from . import access


class LoginWriteSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128)


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


router = SimpleRouter()
router.register("logins", AppLoginViewSet, basename="app-login")
urlpatterns = router.urls
