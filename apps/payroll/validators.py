"""What a run may be started on, and by whom."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.core.errors import PermissionDenied

from .models import ScopeKind


def require_scope(actor, permission: str, run_scope: str, scope_id: int | None,
                  branch_id: int | None = None) -> None:
    """A run limited to a branch needs the permission there; any other, in every branch."""
    if actor is None:
        return
    if run_scope == ScopeKind.BRANCH:
        actor.require(permission, branch=scope_id)
    elif branch_id is not None:
        actor.require(permission, branch=branch_id)
    elif actor.branch_ids(permission) is not None:
        raise PermissionDenied(_("This needs the permission in every branch."),
                               code="PAYROLL_ALL_BRANCHES")
    else:
        actor.require(permission)
