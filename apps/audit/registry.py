"""The foundation data whose every change is recorded (installed by audit.0002_triggers).

Apps added later record their own models with the `AuditModel` migration operation
(apps/audit/triggers.py) in their migrations; the isolation suite checks that every tenant
model is either audited or knowingly left out. Documents are not here: posted documents are
never edited (they are cancelled, which they record themselves).

model label → columns to leave out.
"""

AUDITED: dict[str, tuple[str, ...]] = {
    "org.TenantProfile": (),
    "org.Branch": (),
    "iam.Membership": (),
    "iam.Role": (),
    "iam.RolePermission": (),
    "iam.MembershipRole": (),
    "iam.MembershipRoleBranch": (),
    "iam.MembershipLimit": (),
}
UPDATES_ONLY: set[str] = set()
