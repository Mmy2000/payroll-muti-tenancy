"""A plan's limits on members, set in the platform console, in two kinds:
* office users: anyone holding a role other than the built-in "Employee (app)" one;
* app logins: employees' own logins to the mobile app, holding only that role
  (apps/mobile/services/access.py).
A member is counted while active; suspended ones free their place.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext as _

from apps.core.errors import DomainError
from apps.platform.tenants.selectors import current_tenant

from .catalog import EMPLOYEE
from .models import Membership, MembershipStatus, Role


def is_app_login(role_codes: Iterable[str]) -> bool:
    """Roles that make an app login: the Employee (app) role and nothing else."""
    codes = set(role_codes)
    return bool(codes) and codes <= {EMPLOYEE}


def _app_only_members():
    return (Membership.objects.filter(roles__role__code=EMPLOYEE)
            .exclude(roles__role__in=Role.objects.exclude(code=EMPLOYEE)))


def active_members():
    return Membership.objects.filter(status=MembershipStatus.ACTIVE)


def office_users() -> int:
    return active_members().exclude(pk__in=_app_only_members().values("pk")).count()


def app_logins() -> int:
    return active_members().filter(pk__in=_app_only_members().values("pk")).count()


def check_user_limit() -> None:
    tenant = current_tenant()
    limit = tenant.user_limit if tenant else None
    if limit is not None and office_users() >= limit:
        raise DomainError(
            _("Your plan allows %(limit)s users. Contact us to add more.")
            % {"limit": limit}, code="PLAN_USER_LIMIT")


def check_app_login_limit() -> None:
    tenant = current_tenant()
    limit = tenant.app_login_limit if tenant else None
    if limit is not None and app_logins() >= limit:
        raise DomainError(
            _("Your plan allows %(limit)s app logins. Contact us to add more.")
            % {"limit": limit}, code="PLAN_APP_LOGIN_LIMIT")


def check_room_for(role_codes: Iterable[str]) -> None:
    """Before one more active member with these roles: the limit of their kind."""
    if is_app_login(role_codes):
        check_app_login_limit()
    else:
        check_user_limit()
