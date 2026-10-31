"""Row-level security and same-tenant guards on the sign-in QRs and the phones signed in, and the
QR permission for built-in roles of existing clients. The History shows who gave out a QR and who
signed a phone out, never a code's fingerprint."""

from django.db import migrations

from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS
from apps.iam.migration_helpers import grant_to_system_roles


def _secure():
    for model in ("AppDevice", "AppLinkCode"):
        yield EnableTenantRLS(model)
        yield GuardTenantFKs(model)
    yield AuditModel("AppDevice", ignore=("last_seen_at",))
    yield AuditModel("AppLinkCode", ignore=("code_hash",))


class Migration(migrations.Migration):
    dependencies = [
        ("mobile", "0003_qr_sign_in"),
        ("audit", "0003_triggers"),
        ("iam", "0003_rls_and_membership_count"),
    ]

    operations = [
        *_secure(),
        migrations.RunPython(grant_to_system_roles("mobile.qr."), migrations.RunPython.noop),
    ]
