"""What the evaluations API reads and writes: the shapes of its requests and answers."""

from __future__ import annotations

from rest_framework import serializers


class EvaluationWriteSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    year = serializers.IntegerField()
    evaluated_on = serializers.DateField()
    note_1 = serializers.CharField(allow_blank=True, default="", max_length=5000)
    note_2 = serializers.CharField(allow_blank=True, default="", max_length=5000)
    note_3 = serializers.CharField(allow_blank=True, default="", max_length=5000)
    note_4 = serializers.CharField(allow_blank=True, default="", max_length=5000)
