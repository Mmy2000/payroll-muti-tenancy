"""What the audit trail records, from the database and the models: no table name is written by
hand. A table is audited when it carries the audit trigger (installed by the migrations:
audit.0003 and the `AuditModel` operation), so the screens always match what is recorded.

* `audited_models()`: db table → model, for every audited table.
* `label(model)`: what the screens call its rows (apps/audit/labels.py).
* `parts(model)`: the audited models that belong to one of its records (deleted with it: a
  foreign key with CASCADE), e.g. an employee's pay changes and working hours. A record's
  history shows theirs too.
"""

from __future__ import annotations

from functools import cache

from django.apps import apps
from django.db import connection, models

from .labels import TABLES
from .triggers import AUDIT_TRIGGER


@cache
def audited_tables() -> frozenset[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                       "WHERE t.tgname = %s AND NOT t.tgisinternal", [AUDIT_TRIGGER])
        return frozenset(row[0] for row in cursor.fetchall())


def audited_models() -> dict[str, type[models.Model]]:
    tables = audited_tables()
    return {model._meta.db_table: model for model in apps.get_models()
            if model._meta.db_table in tables}


def model_for(table: str) -> type[models.Model] | None:
    return audited_models().get(table)


def label(model: type[models.Model]) -> str:
    return str(TABLES.get(model._meta.label) or model._meta.verbose_name.capitalize())


def choices() -> list[tuple[str, str]]:
    """(db table, label) for the "What" filter, by label."""
    return sorted(((table, label(model)) for table, model in audited_models().items()),
                  key=lambda pair: pair[1])


def parts(model: type[models.Model]) -> list[tuple[type[models.Model], str]]:
    """(audited model, column of its foreign key to `model`) for each part of a record."""
    found = []
    for other in audited_models().values():
        for field in other._meta.concrete_fields:
            if (field.many_to_one and field.related_model is model
                    and field.remote_field.on_delete is models.CASCADE):
                found.append((other, field.column))
    return found
