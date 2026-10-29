"""Row-level security and same-tenant guards on notifications (not audited: they are a record
of what was said, written once and only marked read)."""

from django.db import migrations

from apps.audit.triggers import GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
        ("audit", "0003_triggers"),
    ]

    operations = [EnableTenantRLS("Notification"), GuardTenantFKs("Notification")]
