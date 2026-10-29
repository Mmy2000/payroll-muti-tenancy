"""The export permission for the built-in roles of existing clients (new clients get it from
the role templates)."""

from django.db import migrations

from apps.iam.migration_helpers import grant_to_system_roles


class Migration(migrations.Migration):
    dependencies = [
        ("iam", "0003_rls_and_membership_count"),
        ("tenants", "0002_plans"),
    ]

    operations = [migrations.RunPython(grant_to_system_roles("reports."),
                                       migrations.RunPython.noop)]
