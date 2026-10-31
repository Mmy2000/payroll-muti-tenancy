"""What the messaging API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers


class WordingSerializer(serializers.Serializer):
    payslip_message = serializers.CharField(max_length=2000)
    gap_seconds = serializers.IntegerField(default=10)


class TestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=30)


class PayslipsSerializer(serializers.Serializer):
    run_id = serializers.IntegerField()
    slip_ids = serializers.ListField(child=serializers.IntegerField(), required=False,
                                     default=list)
    again = serializers.BooleanField(default=False)
