"""Pay items given to employees become schedules (docs/payroll-design.md §4): each monthly entry
becomes a monthly assignment over that month."""

import calendar

from django.db import migrations, models

from apps.core.migration_helpers import for_each_tenant


def to_ranges(apps, schema_editor):
    Assignment = apps.get_model("compensation", "PayItemAssignment")

    def convert(tenant_id, db):
        for row in Assignment.objects.using(db).filter(tenant_id=tenant_id):
            last = calendar.monthrange(row.month.year, row.month.month)[1]
            row.starts_on, row.ends_on = row.month, row.month.replace(day=last)
            row.frequency = "monthly"
            row.save(update_fields=["starts_on", "ends_on", "frequency"])

    for_each_tenant(apps, schema_editor, convert)


class Migration(migrations.Migration):
    dependencies = [("compensation", "0005_entry_rls"), ("org", "0002_rls"),
                    ("employees", "0006_wage_type_pay_frequency")]

    operations = [
        migrations.RemoveConstraint(model_name="payitementry",
                                    name="compensation_entry_once_a_month_uniq"),
        migrations.RemoveConstraint(model_name="payitementry",
                                    name="compensation_entry_values_check"),
        migrations.RemoveIndex(model_name="payitementry", name="compensation_entry_month_idx"),
        migrations.RenameModel("PayItemEntry", "PayItemAssignment"),
        migrations.AlterField(
            model_name="payitemassignment", name="employee",
            field=models.ForeignKey(on_delete=models.deletion.PROTECT,
                                    related_name="pay_item_assignments",
                                    to="employees.employee")),
        migrations.AlterField(
            model_name="payitemassignment", name="item",
            field=models.ForeignKey(on_delete=models.deletion.PROTECT,
                                    related_name="assignments", to="compensation.payitem")),
        migrations.AddField(
            model_name="payitemassignment", name="frequency",
            field=models.CharField(choices=[("once", "Once"), ("period", "Every pay period"),
                                            ("monthly", "Every month"), ("weekly", "Every week")],
                                   default="monthly", max_length=8)),
        migrations.AddField(model_name="payitemassignment", name="starts_on",
                            field=models.DateField(null=True)),
        migrations.AddField(model_name="payitemassignment", name="ends_on",
                            field=models.DateField(blank=True, null=True)),
        migrations.RunPython(to_ranges, migrations.RunPython.noop),
        migrations.AlterField(model_name="payitemassignment", name="starts_on",
                              field=models.DateField()),
        migrations.RemoveField(model_name="payitemassignment", name="month"),
        migrations.AlterModelOptions(name="payitemassignment",
                                     options={"ordering": ["-starts_on", "employee_id"]}),
        migrations.AddIndex(
            model_name="payitemassignment",
            index=models.Index(fields=["tenant", "employee", "starts_on"],
                               name="compensation_assign_emp_idx")),
        migrations.AddConstraint(
            model_name="payitemassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0))
                & (models.Q(("ends_on__isnull", True))
                   | models.Q(("ends_on__gte", models.F("starts_on"))))
                & (~models.Q(("frequency", "once"))
                   | models.Q(("ends_on", models.F("starts_on")))),
                name="compensation_assignment_values_check")),
    ]
