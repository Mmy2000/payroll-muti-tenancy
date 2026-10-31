"""Which login is which employee (`Employee.member`, PayRole: `Users.emp`), for the mobile app:
* an app login: a member made for the app only, with the built-in "Employee (app)" role, given
  from the employee's page (give_login);
* an existing user linked to the employee they are, from the user's form (link_member), for
  someone who works in the office and also uses the app as an employee.

Either is a users' matter (`admin.users.manage`) about an employee one may manage
(`employees.employee.manage` in their branch)."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.errors import DomainError, NotFound, ValidationError
from apps.employees.models import Employee
from apps.employees.permissions import MANAGE as EMPLOYEES_MANAGE
from apps.employees.selectors import get_employee
from apps.iam import catalog as iam_catalog
from apps.iam import services as iam
from apps.iam.limits import is_app_login
from apps.iam.models import MembershipStatus, Role

USERS = "admin.users.manage"


def _role() -> Role:
    role = Role.objects.filter(code=iam_catalog.EMPLOYEE).first()
    if role is None:  # a client set up before the role existed and not migrated: make it
        role = Role.objects.create(code=iam_catalog.EMPLOYEE, name=_("Employee (app)"),
                                   is_system=True)
        iam.set_role_permissions(role, [iam_catalog.APP_SIGNIN])
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
    """The employee is no longer linked to a login. An app login (made for the app only) stops
    working: it is suspended, kept on record. A user who also works in the office keeps their
    login and only stops being this employee."""
    with transaction.atomic():
        employee = get_employee(employee_id, actor, EMPLOYEES_MANAGE, lock=True)
        if actor is not None:
            actor.require(USERS)
            actor.require(EMPLOYEES_MANAGE, branch=employee.branch_id)
        if employee.member_id is None:
            raise NotFound(_("This employee has no login."))
        if is_app_login(employee.member.roles.values_list("role__code", flat=True)):
            iam.set_member_status(employee.member_id, MembershipStatus.SUSPENDED, actor=actor)
        employee.member = None
        employee.save(update_fields=["member", "updated_at"])


def link_member(member_id: int, employee_id: int | None, *, actor=None) -> None:
    """Link a user to the employee they are (PayRole: the user's `emp`), or unlink them (None):
    the app then shows them that employee's attendance, leave and payslips. The employee must
    still be working and not be linked to another user; a user is one employee at most, so
    linking moves the link."""
    with transaction.atomic():
        current = Employee.objects.select_for_update().filter(member_id=member_id).first()
        if (current.pk if current else None) == employee_id:
            return
        if actor is not None:
            actor.require(USERS)
        if current is not None:
            if actor is not None:
                actor.require(EMPLOYEES_MANAGE, branch=current.branch_id)
            current.member = None
            current.save(update_fields=["member", "updated_at"])
        if employee_id is None:
            return
        employee = get_employee(employee_id, actor, EMPLOYEES_MANAGE, lock=True)
        if actor is not None:
            actor.require(EMPLOYEES_MANAGE, branch=employee.branch_id)
        if employee.left_on is not None and employee.left_on < timezone.localdate():
            raise ValidationError(_("Please correct the highlighted fields."),
                                  code="MOBILE_LINK_LEFT",
                                  fields={"employee": [_("This employee has left.")]})
        if employee.member_id is not None:
            raise ValidationError(
                _("Please correct the highlighted fields."), code="MOBILE_LINK_TAKEN",
                fields={"employee": [_("Already linked to the user %(username)s.")
                                     % {"username": employee.member.username}]})
        employee.member_id = member_id
        employee.save(update_fields=["member", "updated_at"])


def can_link(actor) -> bool:
    """Whether to offer the employee link on the user form: the mobile app is on for the client
    and the actor may manage users and employees."""
    return actor.can(iam_catalog.APP_SIGNIN) and actor.can(USERS) and actor.can(EMPLOYEES_MANAGE)


def link_choices(actor, member_id: int | None) -> list[Employee]:
    """Employees the actor may link (working, theirs to manage, not linked to anyone), plus the
    one this user is already linked to, whatever it is: saving the form unchanged must keep it."""
    from apps.employees.selectors import visible_employees

    free = (visible_employees(actor, EMPLOYEES_MANAGE).filter(member__isnull=True)
            .exclude(left_on__lt=timezone.localdate()))
    mine = Employee.objects.filter(member_id=member_id) if member_id else Employee.objects.none()
    return sorted({*free, *mine}, key=lambda employee: employee.code)
