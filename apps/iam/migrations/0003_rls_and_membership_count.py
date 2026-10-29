"""Row-level security on the tenant's identity tables, and how many workspaces each login
belongs to (ADR-022). A workspace can't see the others' memberships (row-level security), so a
trigger on iam_membership keeps the number on the global user row."""

from django.db import migrations

from apps.core.tenancy.rls import EnableTenantRLS

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION iam_membership_count() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    UPDATE iam_user SET membership_count = membership_count + 1 WHERE id = NEW.user_id;
  END IF;
  IF TG_OP IN ('DELETE', 'UPDATE') THEN
    UPDATE iam_user SET membership_count = membership_count - 1 WHERE id = OLD.user_id;
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER iam_membership_count AFTER INSERT OR DELETE OR UPDATE OF user_id
  ON iam_membership FOR EACH ROW EXECUTE FUNCTION iam_membership_count();
"""
DROP_SQL = """
DROP TRIGGER IF EXISTS iam_membership_count ON iam_membership;
DROP FUNCTION IF EXISTS iam_membership_count();
"""


class Migration(migrations.Migration):
    dependencies = [("iam", "0002_initial")]

    operations = [
        EnableTenantRLS("Membership"),
        EnableTenantRLS("Role"),
        EnableTenantRLS("RolePermission"),
        EnableTenantRLS("MembershipRole"),
        EnableTenantRLS("MembershipRoleBranch"),
        EnableTenantRLS("MembershipLimit"),
        EnableTenantRLS("SignInEvent"),
        EnableTenantRLS("Shortcut"),
        migrations.RunSQL(TRIGGER_SQL, DROP_SQL),
    ]
