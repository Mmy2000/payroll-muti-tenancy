"""What a bulk change answers. Its request is GroupFields (serializers.py)."""

from rest_framework.response import Response


def outcome_response(outcome) -> Response:
    """A preview (200) or what was saved (201): the rows, with their problems and warnings."""
    return Response(outcome.as_dict(), status=201 if outcome.saved else 200)
