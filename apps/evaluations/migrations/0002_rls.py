"""Row-level security, same-tenant guards and the audit trail on evaluations; their permissions
for built-in roles of existing clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles


class Migration(migrations.Migration):
    dependencies = [
        ("evaluations", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        EnableTenantRLS("Evaluation"),
        GuardTenantFKs("Evaluation"),
        AuditModel("Evaluation"),
        migrations.RunPython(grant_to_system_roles("evaluations."), migrations.RunPython.noop),
    ]
