"""Row-level security, same-tenant guard and audit trail on pay items."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [
        ("compensation", "0001_initial"),
        ("audit", "0003_triggers"),
    ]

    operations = [
        EnableTenantRLS("PayItem"),
        GuardTenantFKs("PayItem"),
        AuditModel("PayItem"),
    ]
