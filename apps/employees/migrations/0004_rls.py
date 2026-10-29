"""Row-level security, same-tenant guards and audit trail on employees and their history."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0003_initial"),
        ("audit", "0003_triggers"),
    ]

    operations = [
        EnableTenantRLS("Employee"),
        GuardTenantFKs("Employee"),
        AuditModel("Employee"),
        EnableTenantRLS("Compensation"),
        GuardTenantFKs("Compensation"),
        AuditModel("Compensation"),
        EnableTenantRLS("WorkSchedule"),
        GuardTenantFKs("WorkSchedule"),
        AuditModel("WorkSchedule"),
    ]
