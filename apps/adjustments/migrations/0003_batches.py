"""Batches of incentives and penalties (draft → approved, reopened, cancelled, corrected): each
earlier group of entries (the same `batch` uuid and status) becomes an approved or cancelled
batch, with its rows pointing at it; the approve permission for built-in roles of existing
clients."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.migration_helpers import for_each_tenant
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles

KINDS = [("incentive", "Incentive"), ("penalty", "Penalty")]
METHODS = [("fixed", "Fixed amount"), ("percent", "Percentage of salary"),
           ("days", "Days of pay"), ("hours", "Hours of pay")]


def to_batches(apps, schema_editor):
    Adjustment = apps.get_model("adjustments", "Adjustment")
    AdjustmentBatch = apps.get_model("adjustments", "AdjustmentBatch")

    def move(tenant_id, db):
        rows = Adjustment.objects.using(db).filter(tenant_id=tenant_id).order_by("id")
        groups = {}
        for row in rows:
            groups.setdefault((row.batch, row.status), []).append(row)
        for (_uuid, status), members in groups.items():
            first = members[0]
            batch = AdjustmentBatch.objects.using(db).create(
                tenant_id=tenant_id, kind=first.kind, adjustment_type_id=first.adjustment_type_id,
                date=first.date, method=first.method, quantity=first.quantity,
                reason=first.reason,
                target_kind="employee" if len(members) == 1 else "",
                target_id=first.employee_id if len(members) == 1 else None,
                status="approved" if status == "active" else "cancelled",
                approved_at=first.created_at or timezone.now(), created_by_id=first.created_by_id)
            Adjustment.objects.using(db).filter(pk__in=[m.pk for m in members]).update(
                batch_ref=batch)

    for_each_tenant(apps, schema_editor, move)


class Migration(migrations.Migration):
    dependencies = [
        ("adjustments", "0002_rls"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
        ("tenants", "0002_plans"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AdjustmentBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False,
                                           verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=KINDS, max_length=10)),
                ("date", models.DateField()),
                ("method", models.CharField(choices=METHODS, max_length=8)),
                ("quantity", models.DecimalField(decimal_places=2, max_digits=12)),
                ("reason", models.CharField(blank=True, max_length=300)),
                ("target_kind", models.CharField(blank=True, max_length=10)),
                ("target_id", models.BigIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("approved", "Approved"),
                                                     ("cancelled", "Cancelled")],
                                            default="draft", max_length=10)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("change_reason", models.CharField(blank=True, max_length=300)),
                ("adjustment_type", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name="+",
                    to="adjustments.adjustmenttype")),
                ("approved_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("corrects", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="corrections", to="adjustments.adjustmentbatch")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(
                    db_index=False, editable=False, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to="tenants.tenant")),
                ("updated_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
        migrations.AddIndex(
            model_name="adjustmentbatch",
            index=models.Index(fields=["tenant", "kind", "status", "date"],
                               name="adjustments_batch_list_idx")),
        migrations.AddConstraint(
            model_name="adjustmentbatch",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gte=0),
                                              name="adjustments_batch_quantity_check")),
        EnableTenantRLS("AdjustmentBatch"),
        GuardTenantFKs("AdjustmentBatch"),
        AuditModel("AdjustmentBatch"),

        migrations.AddField(
            model_name="adjustment", name="batch_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name="+", to="adjustments.adjustmentbatch")),
        migrations.RunPython(to_batches, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="adjustment", name="adjustments_batch_idx"),
        migrations.RemoveConstraint(model_name="adjustment", name="adjustments_values_check"),
        migrations.RemoveField(model_name="adjustment", name="batch"),
        migrations.RemoveField(model_name="adjustment", name="status"),
        migrations.RenameField(model_name="adjustment", old_name="batch_ref", new_name="batch"),
        migrations.AlterField(
            model_name="adjustment", name="batch",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name="rows", to="adjustments.adjustmentbatch")),
        migrations.AddField(
            model_name="adjustment", name="corrects",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.PROTECT,
                                    related_name="corrections", to="adjustments.adjustment")),
        migrations.AddConstraint(
            model_name="adjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(corrects__isnull=True, quantity__gt=0, amount__gte=0)
                | models.Q(corrects__isnull=False, quantity__gte=0),
                name="adjustments_values_check")),
        migrations.AddConstraint(
            model_name="adjustment",
            constraint=models.UniqueConstraint(fields=("tenant", "batch", "employee"),
                                               name="adjustments_batch_employee_uniq")),
        GuardTenantFKs("Adjustment"),
        migrations.RunPython(grant_to_system_roles("adjustments.incentive.approve",
                                                   "adjustments.penalty.approve"),
                             migrations.RunPython.noop),
    ]
