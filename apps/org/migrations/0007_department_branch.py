"""Each department belongs to one branch, as in PayRole (`Pfn.br1`). A department goes to the branch
most of its employees are in (the head office when it has none); those in other branches move
to a department of the same name there, so everyone's department is in their own branch."""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Count

from apps.audit.triggers import GuardTenantFKs
from apps.core.migration_helpers import for_each_tenant


def place_departments(apps, schema_editor):
    Branch = apps.get_model("org", "Branch")
    Department = apps.get_model("org", "Department")
    Employee = apps.get_model("employees", "Employee")

    def place(tenant_id, db):
        branches = Branch.objects.using(db).filter(tenant_id=tenant_id)
        head_office = branches.order_by("-is_head_office", "code").first()
        staff = Employee.objects.using(db).filter(tenant_id=tenant_id)
        departments = Department.objects.using(db).filter(tenant_id=tenant_id)
        for department in departments.order_by("code"):
            homes = list(staff.filter(department_id=department.pk).values("branch_id")
                         .annotate(people=Count("pk")).order_by("-people", "branch__code"))
            department.branch_id = homes[0]["branch_id"] if homes else head_office.pk
            department.save(update_fields=["branch"])
            for home in homes[1:]:
                copy = Department.objects.using(db).create(
                    tenant_id=tenant_id, branch_id=home["branch_id"], code=department.code,
                    name=department.name, is_active=department.is_active)
                staff.filter(department_id=department.pk, branch_id=home["branch_id"]).update(
                    department_id=copy.pk)

    for_each_tenant(apps, schema_editor, place)
    # The table is altered next: its deferred foreign key checks must have run by then.
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    dependencies = [("org", "0006_branch_latitude_branch_longitude_branch_radius_m"),
                    ("employees", "0008_guard_member")]

    operations = [
        migrations.RemoveConstraint(model_name="department", name="org_department_code_uniq"),
        migrations.RemoveConstraint(model_name="department", name="org_department_name_uniq"),
        migrations.AddField(
            model_name="department", name="branch",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="departments", to="org.branch")),
        migrations.RunPython(place_departments, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="department", name="branch",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name="departments", to="org.branch")),
        migrations.AlterModelOptions(name="department",
                                     options={"ordering": ["branch__code", "code"]}),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.UniqueConstraint(fields=("tenant", "branch", "code"),
                                               name="org_department_code_uniq")),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.UniqueConstraint(fields=("tenant", "branch", "name"),
                                               name="org_department_name_uniq")),
        GuardTenantFKs("Department"),
    ]
