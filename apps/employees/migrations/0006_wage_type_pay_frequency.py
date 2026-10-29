"""The pay basis splits into a wage type (how pay is counted) and a pay frequency (how often it
is run), docs/payroll-design.md §1: monthly → fixed salary paid monthly; weekly → fixed salary
paid weekly; daily → daily wage paid monthly."""

from django.db import migrations, models

from apps.core.migration_helpers import for_each_tenant

SPLIT = {"monthly": ("fixed", "monthly"), "weekly": ("fixed", "weekly"),
         "daily": ("daily", "monthly")}


def split_basis(apps, schema_editor):
    Compensation = apps.get_model("employees", "Compensation")

    def convert(tenant_id, db):
        for basis, (wage_type, frequency) in SPLIT.items():
            Compensation.objects.using(db).filter(tenant_id=tenant_id, basis=basis).update(
                wage_type=wage_type, pay_frequency=frequency)

    for_each_tenant(apps, schema_editor, convert)


class Migration(migrations.Migration):
    dependencies = [("employees", "0005_grant"), ("org", "0002_rls")]

    operations = [
        migrations.AddField(
            model_name="compensation", name="wage_type",
            field=models.CharField(choices=[("fixed", "Fixed salary"), ("daily", "Daily wage"),
                                            ("hourly", "Hourly wage")],
                                   default="fixed", max_length=8)),
        migrations.AddField(
            model_name="compensation", name="pay_frequency",
            field=models.CharField(choices=[("monthly", "Monthly"),
                                            ("biweekly", "Every two weeks"),
                                            ("weekly", "Weekly")],
                                   default="monthly", max_length=8)),
        migrations.RunPython(split_basis, migrations.RunPython.noop),
        migrations.RemoveField(model_name="compensation", name="basis"),
    ]
