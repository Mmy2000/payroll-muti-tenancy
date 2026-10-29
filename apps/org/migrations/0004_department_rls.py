"""Row-level security, same-tenant guard and audit trail on departments."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [
        ("org", "0003_department"),
        ("audit", "0003_triggers"),
    ]

    operations = [
        EnableTenantRLS("Department"),
        GuardTenantFKs("Department"),
        AuditModel("Department"),
    ]
