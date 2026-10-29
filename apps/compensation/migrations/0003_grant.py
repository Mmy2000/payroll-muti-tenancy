"""Clients provisioned earlier: their built-in roles get the pay item permissions, as a new
client's would (apps.iam.migration_helpers)."""

from django.db import migrations

from apps.iam.migration_helpers import grant_to_system_roles


class Migration(migrations.Migration):
    dependencies = [
        ("compensation", "0002_rls"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [migrations.RunPython(grant_to_system_roles("compensation."), migrations.RunPython.noop)]
