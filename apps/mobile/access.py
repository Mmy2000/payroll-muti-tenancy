"""An employee's own login to the mobile app: a member of the client with the built-in
"Employee (app)" role (the app only), linked to the employee (PayRole: `Users.emp`).

Giving or taking one away is a users' matter (`admin.users.manage`) about an employee one may
manage (`employees.employee.manage` in their branch)."""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import DomainError, NotFound
from apps.employees.services import MANAGE as EMPLOYEES_MANAGE
from apps.employees.services import get_employee
from apps.iam import services as iam
from apps.iam.models import MembershipStatus, Role

USERS = "admin.users.manage"


def _role() -> Role:
    role = Role.objects.filter(code=iam.EMPLOYEE).first()
    if role is None:  # a client set up before the role existed and not migrated: make it
        role = Role.objects.create(code=iam.EMPLOYEE, name=_("Employee (app)"), is_system=True)
        iam.set_role_permissions(role, [iam.APP_SIGNIN])
    return role


def give_login(employee_id: int, username: str, password: str, *, actor=None):
    with transaction.atomic():
        employee = get_employee(employee_id, actor, EMPLOYEES_MANAGE, lock=True)
        if actor is not None:
            actor.require(USERS)
            actor.require(EMPLOYEES_MANAGE, branch=employee.branch_id)
        if employee.member_id is not None:
            raise DomainError(_("This employee already has a login."),
                              code="MOBILE_LOGIN_EXISTS")
        member = iam.create_member(iam.MemberInput(
            username=username, display_name=employee.name, default_branch_id=employee.branch_id,
            roles=(iam.RoleAssignmentInput(_role().pk, (employee.branch_id,)),)),
            password, actor=actor)
        employee.member = member
        employee.save(update_fields=["member", "updated_at"])
    return member


def take_login(employee_id: int, *, actor=None) -> None:
    """The login stops working (the member is suspended, kept on record)."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, EMPLOYEES_MANAGE, lock=True)
        if actor is not None:
            actor.require(USERS)
            actor.require(EMPLOYEES_MANAGE, branch=employee.branch_id)
        if employee.member_id is None:
            raise NotFound(_("This employee has no login."))
        iam.set_member_status(employee.member_id, MembershipStatus.SUSPENDED, actor=actor)
        employee.member = None
        employee.save(update_fields=["member", "updated_at"])
