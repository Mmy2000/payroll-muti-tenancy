"""Row-level security and same-tenant guards on positions, their history, and their permissions
for the built-in roles of existing clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles


class Migration(migrations.Migration):
    dependencies = [
        ("org", "0009_hr_structure"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        EnableTenantRLS("Position"),
        GuardTenantFKs("Position"),
        AuditModel("Position"),
        migrations.RunPython(grant_to_system_roles("org.position."), migrations.RunPython.noop),
    ]
