"""Serializer fields shared by the APIs."""

from datetime import date

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


class MonthField(serializers.Field):
    """A calendar month: "YYYY-MM" (what <input type="month"> sends) or any "YYYY-MM-DD" of it.
    Gives the month's first day; writes "YYYY-MM"."""

    default_error_messages = {"invalid": _("Enter a month as YYYY-MM.")}

    def to_internal_value(self, data):
        try:
            year, month = (int(part) for part in str(data).split("-")[:2])
            return date(year, month, 1)
        except (TypeError, ValueError):
            self.fail("invalid")

    def to_representation(self, value):
        return value.strftime("%Y-%m")
