"""What the devices API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers

from ..services import devices


class DeviceWriteSerializer(serializers.Serializer):
    serial = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=60)
    branch_id = serializers.IntegerField()
    is_active = serializers.BooleanField(default=True)


class AskSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[(k, k) for k in (
        devices.TEST, devices.PULL_USERS, devices.PULL_PUNCHES)])
    start = serializers.DateField(required=False, allow_null=True, default=None)
    end = serializers.DateField(required=False, allow_null=True, default=None)


class LinkSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(allow_null=True)
