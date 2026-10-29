"""Row-level security and same-tenant guards on devices; the audit trail on what people set up
(devices and PIN links; punches and commands are their own record); the device permissions for
built-in roles of existing clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles

AUDITED = {"Device", "DeviceUser"}
MODELS = ["Device", "DeviceUser", "DevicePunch", "DeviceCommand"]


def _secure():
    for model in MODELS:
        yield EnableTenantRLS(model)
        yield GuardTenantFKs(model)
        if model in AUDITED:
            yield AuditModel(model, ignore=("last_seen_at", "last_ip", "info")
                             if model == "Device" else ())


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        *_secure(),
        migrations.RunPython(grant_to_system_roles("devices."), migrations.RunPython.noop),
    ]
