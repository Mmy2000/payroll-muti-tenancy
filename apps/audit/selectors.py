"""What the activity page reads: the trail, and the records it names."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from . import catalog
from .models import AuditAction, AuditEvent


def _record_events(model, row_id: int) -> Q:
    """The record's own events and those of its parts, deleted parts included: every part was
    inserted with the trail on, and its insert event names the record."""
    match = Q(table_name=model._meta.db_table, row_id=row_id)
    for part, column in catalog.parts(model):
        table = part._meta.db_table
        ids = AuditEvent.objects.filter(table_name=table, action=AuditAction.INSERT,
                                        **{f"changes__{column}": row_id}).values("row_id")
        match |= Q(table_name=table, row_id__in=ids)
    return match


def activity_events(table: str, model, *, row_id: int | None = None,
                    user_id: int | None = None, date_from=None,
                    date_to=None) -> QuerySet[AuditEvent]:
    """Newest first. `model` is the audited model of `table`, None when `table` isn't one."""
    events = AuditEvent.objects.select_related("user")
    if table and model is None:
        events = events.none()  # not an audited table: nothing, rather than everything
    elif model is not None and row_id is not None:
        events = events.filter(_record_events(model, row_id))
    elif model is not None:
        events = events.filter(table_name=table)
    if user_id is not None:
        events = events.filter(user_id=user_id)
    if date_from:
        events = events.filter(at__date__gte=date_from)
    if date_to:
        events = events.filter(at__date__lte=date_to)
    return events.order_by("-at", "-id")


def records(model, ids) -> QuerySet:
    return model._default_manager.filter(pk__in=ids)


def record(model, pk: int):
    return model._default_manager.filter(pk=pk).first()
