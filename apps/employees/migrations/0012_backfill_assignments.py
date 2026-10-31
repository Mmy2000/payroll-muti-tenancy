"""Every employee gets their assignments. The first holds what they started with, and each change
the audit trail recorded becomes a row from that day, so transfers made before this table existed
are not lost. Job titles in use become positions; a human may then merge the variants."""

from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import migrations

from apps.core.migration_helpers import for_each_tenant

TRACKED = ("branch_id", "department_id", "job_title")


def _timeline(employee, events, zone) -> dict:
    """{day: the placement from that day}. Events are the card's changes, oldest first."""
    state = {name: getattr(employee, name) for name in TRACKED}
    for event in reversed(events):
        for name in TRACKED:
            if name in event.changes:
                state[name] = event.changes[name][0]
    rows = {employee.hired_on: dict(state)}
    for event in events:
        moved = {name: event.changes[name][1] for name in TRACKED if name in event.changes}
        if moved:
            state.update(moved)
            day = max(event.at.astimezone(zone).date(), employee.hired_on)
            rows[day] = dict(state)
    return rows


def rebuild(apps, tenant_id: int, db: str) -> None:
    Employee = apps.get_model("employees", "Employee")
    EmployeeAssignment = apps.get_model("employees", "EmployeeAssignment")
    Position = apps.get_model("org", "Position")
    TenantProfile = apps.get_model("org", "TenantProfile")
    AuditEvent = apps.get_model("audit", "AuditEvent")

    name = (TenantProfile.objects.using(db).filter(tenant_id=tenant_id)
            .values_list("timezone", flat=True).first())
    zone = ZoneInfo(name or settings.TIME_ZONE)
    events: dict[int, list] = {}
    for event in (AuditEvent.objects.using(db)
                  .filter(tenant_id=tenant_id, table_name="employees_employee", action="U")
                  .order_by("at", "id")):
        events.setdefault(event.row_id, []).append(event)

    positions: dict[str, int] = {}

    def position_of(title: str) -> int | None:
        title = (title or "").strip()
        if not title:
            return None
        if title not in positions:
            positions[title] = Position.objects.using(db).get_or_create(
                tenant_id=tenant_id, name=title)[0].pk
        return positions[title]

    rows = []
    for employee in Employee.objects.using(db).filter(tenant_id=tenant_id):
        if EmployeeAssignment.objects.using(db).filter(employee_id=employee.pk).exists():
            continue
        for day, placed in sorted(_timeline(employee, events.get(employee.pk, []), zone).items()):
            rows.append(EmployeeAssignment(tenant_id=tenant_id, employee_id=employee.pk,
                                           effective_from=day, branch_id=placed["branch_id"],
                                           department_id=placed["department_id"],
                                           job_title=placed["job_title"],
                                           position_id=position_of(placed["job_title"])))
        employee.position_id = position_of(employee.job_title)
        employee.save(update_fields=["position"])
    EmployeeAssignment.objects.using(db).bulk_create(rows)


def forward(apps, schema_editor):
    for_each_tenant(apps, schema_editor, lambda tenant_id, db: rebuild(apps, tenant_id, db))


class Migration(migrations.Migration):
    dependencies = [("employees", "0011_assignment_rls"), ("audit", "0003_triggers")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
