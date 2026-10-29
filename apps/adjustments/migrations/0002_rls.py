"""Row-level security, same-tenant guards and the audit trail on incentives and penalties; their
permissions for built-in roles of existing clients; and their starting types."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.migration_helpers import for_each_tenant
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles


def seed_types(apps, schema_editor):
    from django.utils.translation import gettext as _

    AdjustmentType = apps.get_model("adjustments", "AdjustmentType")

    def add(tenant_id, db):
        if AdjustmentType.objects.using(db).filter(tenant_id=tenant_id).exists():
            return
        rows = [("incentive", 1, _("Performance bonus")), ("incentive", 2, _("Attendance bonus")),
                ("penalty", 1, _("Lateness")), ("penalty", 2, _("Unexcused absence")),
                ("penalty", 3, _("Breaking the rules"))]
        AdjustmentType.objects.using(db).bulk_create([
            AdjustmentType(tenant_id=tenant_id, kind=kind, code=code, name=name)
            for kind, code, name in rows])

    for_each_tenant(apps, schema_editor, add)


class Migration(migrations.Migration):
    dependencies = [
        ("adjustments", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
        ("org", "0002_rls"),
    ]

    operations = [
        EnableTenantRLS("AdjustmentType"),
        GuardTenantFKs("AdjustmentType"),
        AuditModel("AdjustmentType"),
        EnableTenantRLS("Adjustment"),
        GuardTenantFKs("Adjustment"),
        AuditModel("Adjustment"),
        migrations.RunPython(grant_to_system_roles("adjustments."), migrations.RunPython.noop),
        migrations.RunPython(seed_types, migrations.RunPython.noop),
    ]
