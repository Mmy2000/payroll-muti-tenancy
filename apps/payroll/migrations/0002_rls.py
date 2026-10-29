"""Row-level security and same-tenant guards on payroll; the audit trail on calendars, periods,
runs and manual lines (payslips and their lines are written by the engine and frozen with their
run); and the payroll permissions for built-in roles of existing clients."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles

AUDITED = {"PayCalendar", "PayrollPeriod", "PayrollRun", "ManualLine"}
MODELS = ["PayCalendar", "PayrollPeriod", "PayrollRun", "Payslip", "PayslipLine", "ManualLine",
          "PaidSource"]


def _secure():
    for model in MODELS:
        yield EnableTenantRLS(model)
        yield GuardTenantFKs(model)
        if model in AUDITED:
            yield AuditModel(model, ignore=("calculated_at", "earnings", "deductions", "net",
                                            "employer_cost", "skipped")
                             if model == "PayrollRun" else ())


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0001_initial"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        *_secure(),
        migrations.RunPython(grant_to_system_roles("payroll."), migrations.RunPython.noop),
    ]
