"""Row-level security, same-tenant guards and the history of the branches a department is in."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [("org", "0011_department_branches"), ("audit", "0003_triggers")]

    operations = [
        EnableTenantRLS("DepartmentBranch"),
        GuardTenantFKs("DepartmentBranch"),
        AuditModel("DepartmentBranch"),
    ]
