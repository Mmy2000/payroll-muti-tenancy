"""What the browser sends the mobile app's pages."""

from __future__ import annotations

from rest_framework import serializers


class LoginWriteSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128)
