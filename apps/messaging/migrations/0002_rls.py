"""Row-level security and same-tenant guards on WhatsApp; the audit trail on the link and its
wording (messages are their own log); the WhatsApp permissions for built-in roles of existing
clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        EnableTenantRLS("WhatsAppLink"),
        GuardTenantFKs("WhatsAppLink"),
        AuditModel("WhatsAppLink", ignore=("checked_at", "error", "status", "phone")),
        EnableTenantRLS("Message"),
        GuardTenantFKs("Message"),
        migrations.RunPython(grant_to_system_roles("messaging."), migrations.RunPython.noop),
    ]
