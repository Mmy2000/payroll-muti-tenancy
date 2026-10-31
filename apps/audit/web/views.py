"""The activity page: who changed what, and when, across the audited data, or the history of
one record (?table=…&row=…) with the parts that belong to it (an employee's pay and hours, a
loan's installments…). The audited tables come from apps/audit/catalog.py."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time

from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q
from django.shortcuts import render
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from apps.core.templatetags.ui import num
from apps.iam.authz import permission_required
from apps.iam.models import Membership

from .. import catalog
from ..labels import COLUMNS
from ..models import AuditAction, AuditEvent

HIDDEN = "***"


def _name(obj) -> str:
    for attribute in ("label", "display_name", "name", "username", "number", "code",
                      "permission"):
        value = getattr(obj, attribute, None)
        if value:
            return str(value)
    return f"#{obj.pk}"


def _date(value: str):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _when(field, value) -> str | None:
    """A date or time as the trail recorded it (ISO, UTC) in the page's own format and the
    client's clock; None when `value` isn't one."""
    try:
        if isinstance(field, models.DateTimeField):  # before DateField: it is one
            moment = datetime.fromisoformat(value)
            if timezone.is_aware(moment):
                moment = timezone.localtime(moment)
            return formats.date_format(moment, "SHORT_DATETIME_FORMAT")
        if isinstance(field, models.DateField):
            return formats.date_format(date.fromisoformat(value), "SHORT_DATE_FORMAT")
        if isinstance(field, models.TimeField):
            return formats.time_format(time.fromisoformat(value), "TIME_FORMAT")
    except (TypeError, ValueError):
        pass
    return None


class _Labels:
    """Resolves record ids to names in bulk, one query per model."""

    def __init__(self):
        self.wanted: dict[type, set[int]] = defaultdict(set)
        self.names: dict[tuple[type, int], str] = {}

    def want(self, model, pk):
        if pk is not None:
            self.wanted[model].add(int(pk))

    def load(self):
        for model, ids in self.wanted.items():
            for obj in model._default_manager.filter(pk__in=ids):
                self.names[(model, obj.pk)] = _name(obj)

    def get(self, model, pk):
        return self.names.get((model, int(pk)))


def _describe(events) -> list[dict]:
    by_table = catalog.audited_models()
    labels = _Labels()
    for event in events:
        model = by_table.get(event.table_name)
        if model is None:
            continue
        labels.want(model, event.row_id)
        fields = {f.column: f for f in model._meta.concrete_fields}
        for column, value in event.changes.items():
            field = fields.get(column)
            if field is not None and field.is_relation:
                for item in (value if event.action == AuditAction.UPDATE else [value]):
                    if item not in (None, HIDDEN) and str(item).isdigit():
                        labels.want(field.related_model, item)
    labels.load()

    def shown(field, value):
        if value is None or value == "":
            return "—"
        if value == HIDDEN:
            return _("(hidden)")
        if field is not None and field.is_relation and str(value).isdigit():
            return labels.get(field.related_model, value) or f"#{value}"
        if field is not None and field.choices:
            return str(dict(field.flatchoices).get(value, value))
        if isinstance(value, bool):
            return _("Yes") if value else _("No")
        if isinstance(field, models.DecimalField) and isinstance(value, (int, float, str)):
            return num(value, min(field.decimal_places, 4))
        if isinstance(value, (dict, list)):
            return "…" if value else "—"
        return _when(field, value) or str(value)

    rows = []
    for event in events:
        model = by_table.get(event.table_name)
        fields = {f.column: f for f in model._meta.concrete_fields} if model else {}
        changes = []
        for column, value in sorted(event.changes.items()):
            field = fields.get(column)
            label = COLUMNS.get(column) or (
                str(field.verbose_name).capitalize() if field is not None else column)
            if event.action == AuditAction.UPDATE and value == HIDDEN:
                changes.append({"label": label, "old": _("(hidden)"), "new": _("(hidden)")})
            elif event.action == AuditAction.UPDATE:
                changes.append({"label": label, "old": shown(field, value[0]),
                                "new": shown(field, value[1])})
            else:
                changes.append({"label": label, "new": shown(field, value)})
        name = labels.get(model, event.row_id) if model else None
        if name is None:  # deleted since: name it from what was recorded
            recorded = event.changes
            name = next((str(recorded[key]) for key in ("name", "display_name", "username",
                                                        "number", "code", "permission")
                         if isinstance(recorded.get(key), str)), f"#{event.row_id}")
        rows.append({"event": event, "what": catalog.label(model) if model else
                     event.table_name, "name": name, "changes": changes})
    return rows


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


@permission_required("admin.audit.history")
def activity(request):
    events = AuditEvent.objects.select_related("user")
    table = request.GET.get("table", "")
    row = request.GET.get("row", "")
    who = request.GET.get("user", "")
    date_from, date_to = _date(request.GET.get("from", "")), _date(request.GET.get("to", ""))
    model = catalog.model_for(table) if table else None
    if table and model is None:
        events = events.none()  # not an audited table: nothing, rather than everything
    elif model is not None and row.isdigit():
        events = events.filter(_record_events(model, int(row)))
    elif model is not None:
        events = events.filter(table_name=table)
    if who.isdigit():
        events = events.filter(user_id=int(who))
    if date_from:
        events = events.filter(at__date__gte=date_from)
    if date_to:
        events = events.filter(at__date__lte=date_to)
    page = Paginator(events.order_by("-at", "-id"), 40).get_page(request.GET.get("page"))
    rows = _describe(list(page.object_list))
    record = None
    if model is not None and row.isdigit():
        obj = model._default_manager.filter(pk=int(row)).first()
        own = next((r for r in rows if r["event"].table_name == table), None)
        record = {"what": catalog.label(model), "name": _name(obj) if obj else
                  own["name"] if own else f"#{row}"}
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "audit/activity.html", {
        "page": page, "rows": rows, "record": record, "tables": catalog.choices(),
        "members": Membership.objects.select_related("user").order_by("username"),
        "filters": {"table": table, "row": row, "user": who, "from": date_from, "to": date_to},
        "query": query.urlencode(),
    })
