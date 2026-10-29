"""Row-level security, same-tenant guards and audit trail on the pay policies."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [
        ("policies", "0001_initial"),
        ("audit", "0003_triggers"),
    ]

    operations = [
        EnableTenantRLS("LatenessPolicy"),
        GuardTenantFKs("LatenessPolicy"),
        AuditModel("LatenessPolicy"),
        EnableTenantRLS("LatenessBand"),
        GuardTenantFKs("LatenessBand"),
        AuditModel("LatenessBand"),
        EnableTenantRLS("OvertimePolicy"),
        GuardTenantFKs("OvertimePolicy"),
        AuditModel("OvertimePolicy"),
        EnableTenantRLS("OvertimeBand"),
        GuardTenantFKs("OvertimeBand"),
        AuditModel("OvertimeBand"),
        EnableTenantRLS("TaxTable"),
        GuardTenantFKs("TaxTable"),
        AuditModel("TaxTable"),
        EnableTenantRLS("TaxBracket"),
        GuardTenantFKs("TaxBracket"),
        AuditModel("TaxBracket"),
        EnableTenantRLS("InsuranceRate"),
        GuardTenantFKs("InsuranceRate"),
        AuditModel("InsuranceRate"),
        EnableTenantRLS("PublicHoliday"),
        GuardTenantFKs("PublicHoliday"),
        AuditModel("PublicHoliday"),
    ]
