"""A plan's limit on branches."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.core.errors import DomainError
from apps.platform.tenants.selectors import current_tenant

from .models import Branch


def check_branch_limit() -> None:
    tenant = current_tenant()
    limit = tenant.branch_limit if tenant else None
    if limit is not None and Branch.objects.filter(is_active=True).count() >= limit:
        raise DomainError(
            _("Your plan allows %(limit)s branches. Contact us to add more.")
            % {"limit": limit}, code="PLAN_BRANCH_LIMIT")
