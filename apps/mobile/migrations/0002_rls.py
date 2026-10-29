"""Row-level security and same-tenant guards on the mobile app's records (the phone a proof
comes from is audited; nonces and tracks are high-volume records of their own); the built-in
"Employee (app)" role and the mobile permissions for built-in roles of existing clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.migration_helpers import for_each_tenant
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles

MODELS = ["BiometricEnrollment", "BiometricNonce", "TrackSession", "TrackPoint"]


def employee_role(apps, schema_editor):
    from django.utils.translation import gettext as _

    Role = apps.get_model("iam", "Role")
    RolePermission = apps.get_model("iam", "RolePermission")

    def add(tenant_id, db):
        role, created = Role.objects.using(db).get_or_create(
            tenant_id=tenant_id, code="employee",
            defaults={"name": _("Employee (app)"), "is_system": True})
        if created:
            RolePermission.objects.using(db).create(tenant_id=tenant_id, role=role,
                                                    permission="mobile.signin")

    for_each_tenant(apps, schema_editor, add)


def _secure():
    for model in MODELS:
        yield EnableTenantRLS(model)
        yield GuardTenantFKs(model)
    yield AuditModel("BiometricEnrollment", ignore=("last_used_at",))


class Migration(migrations.Migration):
    dependencies = [
        ("mobile", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
        ("employees", "0007_employee_member_employee_photo"),
        ("attendance", "0003_punch_direction_punch_latitude_punch_longitude"),
    ]

    operations = [
        *_secure(),
        migrations.RunPython(employee_role, migrations.RunPython.noop),
        migrations.RunPython(grant_to_system_roles("mobile."), migrations.RunPython.noop),
    ]
