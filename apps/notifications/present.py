"""A notification as the screens get it: the same shape from the API, the page and the stream."""

from __future__ import annotations

from django.utils.timesince import timesince
from django.utils.translation import gettext as _

from .kinds import look


def item(row) -> dict:
    appearance = look(row.kind)
    return {"id": row.pk, "kind": row.kind, "title": row.title, "body": row.body,
            "url": row.url, "read": row.read_at is not None, "icon": appearance.icon,
            "tone": appearance.tone, "at": row.created_at.isoformat(),
            "ago": _("%(time)s ago") % {"time": timesince(row.created_at)}}
