"""A department now spans branches. Departments of the same name, one per branch until now, become
one, keeping the branches they were in. Everything that pointed at them follows, and batches and
runs given to a department keep the branch they meant, so nobody's history widens. A department
code becomes the company's, so one that two departments shared is renumbered.

This can't be undone by reversing the migration: the merged rows are gone."""

from django.db import migrations
from django.db.models import Max

from apps.core.migration_helpers import for_each_tenant

POINTING_AT_IT = (("employees", "Employee"), ("employees", "EmployeeAssignment"),
                  ("payroll", "Payslip"), ("org", "Position"))


def merge(apps, tenant_id: int, db: str) -> None:
    Department = apps.get_model("org", "Department")
    DepartmentBranch = apps.get_model("org", "DepartmentBranch")
    AdjustmentBatch = apps.get_model("adjustments", "AdjustmentBatch")
    PayrollRun = apps.get_model("payroll", "PayrollRun")

    rows = list(Department.objects.using(db).filter(tenant_id=tenant_id).order_by("code", "id"))
    for row in rows:
        AdjustmentBatch.objects.using(db).filter(
            tenant_id=tenant_id, target_kind="department", target_id=row.pk,
            target_branch_id__isnull=True).update(target_branch_id=row.branch_id)
        PayrollRun.objects.using(db).filter(
            tenant_id=tenant_id, scope="department", scope_id=row.pk,
            scope_branch_id__isnull=True).update(scope_branch_id=row.branch_id)

    kept: dict[str, object] = {}
    for row in rows:
        main = kept.setdefault(row.name.strip().casefold(), row)
        DepartmentBranch.objects.using(db).get_or_create(
            tenant_id=tenant_id, department_id=main.pk, branch_id=row.branch_id)
        if main is row:
            continue
        for app, model in POINTING_AT_IT:
            apps.get_model(app, model).objects.using(db).filter(
                tenant_id=tenant_id, department_id=row.pk).update(department_id=main.pk)
        AdjustmentBatch.objects.using(db).filter(
            tenant_id=tenant_id, target_kind="department", target_id=row.pk).update(
            target_id=main.pk)
        PayrollRun.objects.using(db).filter(
            tenant_id=tenant_id, scope="department", scope_id=row.pk).update(scope_id=main.pk)
        main.is_active = main.is_active or row.is_active
        row.delete()

    top = (Department.objects.using(db).filter(tenant_id=tenant_id)
           .aggregate(top=Max("code"))["top"] or 0)
    taken = set()
    for main in kept.values():
        if main.code in taken:
            top += 1
            main.code = top
        taken.add(main.code)
        main.save(update_fields=["code", "is_active"])


def forward(apps, schema_editor):
    for_each_tenant(apps, schema_editor, lambda tenant_id, db: merge(apps, tenant_id, db))


class Migration(migrations.Migration):
    dependencies = [
        ("org", "0012_department_branch_rls"),
        ("employees", "0012_backfill_assignments"),
        ("payroll", "0005_department_branches"),
        ("adjustments", "0004_department_branches"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
