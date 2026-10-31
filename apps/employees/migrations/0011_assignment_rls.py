"""Row-level security, same-tenant guards and the history of assignments, and the guard on the
employee's new position."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0010_hr_structure"),
        ("org", "0010_position_rls"),
        ("audit", "0003_triggers"),
    ]

    operations = [
        EnableTenantRLS("EmployeeAssignment"),
        GuardTenantFKs("EmployeeAssignment"),
        AuditModel("EmployeeAssignment"),
        GuardTenantFKs("Employee"),
    ]
