"""The same-tenant guard of employees again: they now point at their app login (Membership)."""

from django.db import migrations

from apps.audit.triggers import GuardTenantFKs


class Migration(migrations.Migration):
    dependencies = [("employees", "0007_employee_member_employee_photo")]

    operations = [GuardTenantFKs("Employee")]
