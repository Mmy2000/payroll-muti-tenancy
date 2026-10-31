"""Which employee each user on a device is."""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import DomainError, NotFound, invalid_fields
from apps.employees.models import Employee

from ..models import DeviceUser
from ..permissions import MANAGE
from .sync import to_attendance


def link(device_user_id: int, employee_id: int | None, *, actor=None) -> DeviceUser:
    """Link a PIN to an employee of the same branch (or unlink it). Once its punches are in
    someone's attendance the link stays: correct those days with attendance entries."""
    with transaction.atomic():
        user = DeviceUser.objects.select_for_update().filter(pk=device_user_id).first()
        if user is None or (actor is not None
                            and not actor.can(MANAGE, branch=user.branch_id)):
            raise NotFound(_("Not found."))
        if user.employee_id == employee_id:
            return user
        if user.punches.filter(punch__isnull=False).exists():
            raise DomainError(_("This PIN's punches are already in an employee's attendance: "
                                "the link can't change."), code="DEVICES_LINK_USED")
        employee = None
        if employee_id is not None:
            employee = Employee.objects.filter(pk=employee_id, branch_id=user.branch_id).first()
            if employee is None:
                raise invalid_fields({"employee_id": [_("Choose an employee of the device's "
                                                  "branch.")]})
            if DeviceUser.objects.filter(branch_id=user.branch_id, employee=employee).exclude(
                    pk=user.pk).exists():
                raise invalid_fields({"employee_id": [_("This employee already has a PIN on this "
                                                  "branch's devices.")]})
        user.employee = employee
        user.updated_by = getattr(actor, "user", None)
        user.save(update_fields=["employee", "updated_by", "updated_at"])
        to_attendance(user)
    return user


def link_by_code(branch_id: int, *, actor=None) -> int:
    """Link every unlinked PIN that is an employee's code in the branch (PayRole auto_link).
    Returns how many were linked."""
    if actor is not None:
        actor.require(MANAGE, branch=branch_id)
    linked = 0
    with transaction.atomic():
        taken = set(DeviceUser.objects.filter(branch_id=branch_id, employee__isnull=False)
                    .values_list("employee_id", flat=True))
        people = {str(e.code): e for e in Employee.objects.filter(
            branch_id=branch_id, left_on__isnull=True).exclude(pk__in=taken)}
        for user in DeviceUser.objects.select_for_update().filter(branch_id=branch_id,
                                                                  employee__isnull=True):
            employee = people.pop(user.pin.lstrip("0") or "0", None)
            if employee is not None:
                user.employee = employee
                user.save(update_fields=["employee", "updated_at"])
                to_attendance(user)
                linked += 1
    return linked
