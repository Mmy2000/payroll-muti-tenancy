"""Helpers for data migrations that touch every client's rows.

Row-level security applies to the migrating role too, so each client's rows are only visible
with `app.tenant_id` set to it. `for_each_tenant` does that around a function, in the client's
language (for seeded names):

    def seed(apps, schema_editor):
        LeaveType = apps.get_model("attendance", "LeaveType")

        def add(tenant_id, db):
            if not LeaveType.objects.using(db).filter(tenant_id=tenant_id).exists():
                LeaveType.objects.using(db).create(tenant_id=tenant_id, name=_("Annual"), ...)

        for_each_tenant(apps, schema_editor, add)

Historical models don't stamp the tenant: set `tenant_id` yourself.
"""

from __future__ import annotations

from collections.abc import Callable

from django.utils import translation


def for_each_tenant(apps, schema_editor, run: Callable[[int, str], None]) -> None:
    Tenant = apps.get_model("tenants", "Tenant")
    TenantProfile = apps.get_model("org", "TenantProfile")
    connection = schema_editor.connection
    db = connection.alias
    try:
        for tenant_id in Tenant.objects.using(db).values_list("id", flat=True):
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
            locale = (TenantProfile.objects.using(db).filter(tenant_id=tenant_id)
                      .values_list("locale", flat=True).first() or "ar")
            with translation.override(locale):
                run(tenant_id, db)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', '', true)")
