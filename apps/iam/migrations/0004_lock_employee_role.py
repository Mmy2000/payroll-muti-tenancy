"""The Employee (app) role only signs in to the mobile app: a member holding it alone counts as an
app login, so office permissions on it would pass the plan's limit on users."""

from django.db import migrations

from apps.core.migration_helpers import for_each_tenant


def lock(apps, schema_editor):
    RolePermission = apps.get_model("iam", "RolePermission")

    def run(tenant_id, db):
        RolePermission.objects.using(db).filter(tenant_id=tenant_id, role__code="employee").exclude(
            permission="mobile.signin").delete()

    for_each_tenant(apps, schema_editor, run)


class Migration(migrations.Migration):
    dependencies = [("iam", "0003_rls_and_membership_count"), ("org", "0001_initial")]

    operations = [migrations.RunPython(lock, migrations.RunPython.noop)]
