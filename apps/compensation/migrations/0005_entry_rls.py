"""Row-level security, same-tenant guard and the audit trail on pay items given to employees, and
their permissions for built-in roles of existing clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles


class Migration(migrations.Migration):
    dependencies = [
        ("compensation", "0004_payitementry"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        EnableTenantRLS("PayItemEntry"),
        GuardTenantFKs("PayItemEntry"),
        AuditModel("PayItemEntry"),
        migrations.RunPython(grant_to_system_roles("compensation.entry."),
                             migrations.RunPython.noop),
    ]
