"""Row-level security on the audit table, the trigger functions, the audit trail on the
foundation data listed in apps/audit/registry.py, and the same-tenant foreign key guard on every
tenant table so far. Later apps use the `AuditModel` and `GuardTenantFKs` operations."""

from django.db import migrations

from apps.audit.registry import AUDITED, UPDATES_ONLY
from apps.audit.triggers import (
    AUDIT_TRIGGER,
    FUNCTIONS_SQL,
    GUARD_TRIGGER,
    _guard_function,
    audit_sql,
    guard_sql,
    tenant_fk_pairs,
)
from apps.core.tenancy.rls import EnableTenantRLS


def _tenant_models(apps):
    return [model for model in apps.get_models()
            if any(field.name == "tenant" for field in model._meta.fields)]


def install(apps, schema_editor):
    schema_editor.execute(FUNCTIONS_SQL, params=None)  # no params: "%" stays literal
    schema_editor.execute('CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON '
                          '"audit_auditevent" FOR EACH ROW EXECUTE FUNCTION audit_append_only()')
    for label, ignore in AUDITED.items():
        model = apps.get_model(label)
        for sql in audit_sql(model._meta.db_table, ignore=ignore,
                             updates_only=label in UPDATES_ONLY):
            schema_editor.execute(sql)
    for model in _tenant_models(apps):
        for sql in guard_sql(model._meta.db_table, tenant_fk_pairs(model)):
            schema_editor.execute(sql, params=None)


def remove(apps, schema_editor):
    for model in _tenant_models(apps):
        table = model._meta.db_table
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {GUARD_TRIGGER} ON "{table}"')
        schema_editor.execute(f'DROP FUNCTION IF EXISTS "{_guard_function(table)}"()')
    for label in AUDITED:
        table = apps.get_model(label)._meta.db_table
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {AUDIT_TRIGGER} ON "{table}"')
    schema_editor.execute('DROP TRIGGER IF EXISTS audit_append_only ON "audit_auditevent"')


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_initial"),
        ("core", "0003_rls"),
        ("iam", "0003_rls_and_membership_count"),
        ("org", "0002_rls"),
    ]

    operations = [
        EnableTenantRLS("AuditEvent"),
        migrations.RunPython(install, remove),
    ]
