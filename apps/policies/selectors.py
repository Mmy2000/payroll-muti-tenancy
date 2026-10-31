"""Reading one policy."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.core.errors import NotFound


def get_record(model, pk: int):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound(_("Not found."))
    return obj
