"""Parsing "who it's for" (apps.employees.targets) in the API: one target, or a group for a bulk
change."""

from rest_framework import serializers
from rest_framework.response import Response

from apps.employees.targets import GROUP_KINDS, KINDS, Group, Target


class TargetFields(serializers.Serializer):
    """Mix into a write serializer: `target_kind` (employee / department / branch) and
    `target_id`; `target(data)` gives the Target."""

    target_kind = serializers.ChoiceField(choices=[(k, k) for k in KINDS])
    target_id = serializers.IntegerField()

    @staticmethod
    def target(data: dict) -> Target:
        return Target(data.pop("target_kind"), data.pop("target_id"))


class GroupFields(serializers.Serializer):
    """Mix into the write serializer of a bulk change (apps/core/bulk.py): who (`group_kind`:
    employees / department / branch, with `employee_ids` or `group_id`), and whether to only
    preview (`save` false), or to save, leaving out rows that fail (`skip_failed`)."""

    group_kind = serializers.ChoiceField(choices=[(k, k) for k in GROUP_KINDS])
    employee_ids = serializers.ListField(child=serializers.IntegerField(), required=False,
                                         default=list, max_length=2000)
    group_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    save = serializers.BooleanField(default=False)
    skip_failed = serializers.BooleanField(default=False)

    @staticmethod
    def group(data: dict) -> Group:
        return Group(data.pop("group_kind"), tuple(data.pop("employee_ids")),
                     data.pop("group_id"))

    @staticmethod
    def run_options(data: dict) -> dict:
        return {"save": data.pop("save"), "skip_failed": data.pop("skip_failed")}


def outcome_response(outcome) -> Response:
    """A preview (200) or what was saved (201): the rows, with their problems and warnings."""
    return Response(outcome.as_dict(), status=201 if outcome.saved else 200)
