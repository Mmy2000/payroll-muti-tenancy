"""Payslips record where the employee was at the end of the period: existing ones from the
assignment in effect then. Reports of closed months read these from now on."""

from django.db import migrations

from apps.audit.triggers import GuardTenantFKs
from apps.core.migration_helpers import for_each_tenant


def place(apps, tenant_id: int, db: str) -> None:
    Payslip = apps.get_model("payroll", "Payslip")
    EmployeeAssignment = apps.get_model("employees", "EmployeeAssignment")

    history: dict[int, list] = {}
    for row in (EmployeeAssignment.objects.using(db).filter(tenant_id=tenant_id)
                .order_by("effective_from", "id")):
        history.setdefault(row.employee_id, []).append(row)
    slips = list(Payslip.objects.using(db).filter(tenant_id=tenant_id, branch__isnull=True)
                 .select_related("employee", "run__period"))
    for slip in slips:
        rows = [r for r in history.get(slip.employee_id, [])
                if r.effective_from <= slip.run.period.end]
        placed = rows[-1] if rows else slip.employee
        slip.branch_id, slip.department_id = placed.branch_id, placed.department_id
    Payslip.objects.using(db).bulk_update(slips, ["branch", "department"], batch_size=500)


def forward(apps, schema_editor):
    for_each_tenant(apps, schema_editor, lambda tenant_id, db: place(apps, tenant_id, db))


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0003_hr_structure"),
        ("employees", "0012_backfill_assignments"),
        ("audit", "0003_triggers"),
    ]

    operations = [
        GuardTenantFKs("Payslip"),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
