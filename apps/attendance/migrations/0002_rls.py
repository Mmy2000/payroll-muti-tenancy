"""Row-level security and same-tenant guards on attendance; the audit trail on what people
enter (punches are append-only instead, enforced by a trigger); the attendance permissions for
built-in roles of existing clients; and their starting leave types."""

from django.db import migrations
from django.utils import translation

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles

APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION attendance_punch_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'punches are append-only: correct a day with an attendance entry'
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER attendance_punch_append_only BEFORE UPDATE OR DELETE ON attendance_punch
  FOR EACH ROW EXECUTE FUNCTION attendance_punch_append_only();
"""
APPEND_ONLY_DROP = """
DROP TRIGGER IF EXISTS attendance_punch_append_only ON attendance_punch;
DROP FUNCTION IF EXISTS attendance_punch_append_only();
"""


def seed_leave_types(apps, schema_editor):
    from django.utils.translation import gettext as _

    Tenant = apps.get_model("tenants", "Tenant")
    TenantProfile = apps.get_model("org", "TenantProfile")
    LeaveType = apps.get_model("attendance", "LeaveType")
    connection = schema_editor.connection
    db = connection.alias
    for tenant_id in Tenant.objects.using(db).values_list("id", flat=True):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
        if LeaveType.objects.using(db).filter(tenant_id=tenant_id).exists():
            continue
        locale = (TenantProfile.objects.using(db).filter(tenant_id=tenant_id)
                  .values_list("locale", flat=True).first() or "ar")
        with translation.override(locale):
            rows = ((1, _("Annual leave"), True, True), (2, _("Sick leave"), True, False),
                    (3, _("Unpaid leave"), False, False))
            LeaveType.objects.using(db).bulk_create([
                LeaveType(tenant_id=tenant_id, code=code, name=name, paid=paid,
                          uses_annual_balance=balance) for code, name, paid, balance in rows])
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', '', true)")


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
        ("org", "0002_rls"),
    ]

    operations = [
        EnableTenantRLS("Punch"),
        GuardTenantFKs("Punch"),
        migrations.RunSQL(APPEND_ONLY_SQL, APPEND_ONLY_DROP),
        EnableTenantRLS("AttendanceDay"),
        GuardTenantFKs("AttendanceDay"),
        AuditModel("AttendanceDay"),
        EnableTenantRLS("LeaveType"),
        GuardTenantFKs("LeaveType"),
        AuditModel("LeaveType"),
        EnableTenantRLS("LeaveRequest"),
        GuardTenantFKs("LeaveRequest"),
        AuditModel("LeaveRequest"),
        EnableTenantRLS("HourlyLeave"),
        GuardTenantFKs("HourlyLeave"),
        AuditModel("HourlyLeave"),
        migrations.RunPython(grant_to_system_roles("attendance."), migrations.RunPython.noop),
        migrations.RunPython(seed_leave_types, migrations.RunPython.noop),
    ]
