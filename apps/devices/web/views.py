"""Fingerprint device pages. They read and render; every save goes to the JSON API."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render

from apps.employees.selectors import visible_employees
from apps.iam.authz import permission_required
from apps.org.models import Branch

from .. import permissions, selectors
from ..models import DeviceUser
from ..services import sync

RECENT = 50


def _branches(actor):
    allowed = actor.branch_ids(permissions.MANAGE)
    branches = Branch.objects.filter(is_active=True).order_by("code")
    return branches if allowed is None else branches.filter(pk__in=allowed)


@permission_required(permissions.VIEW)
def devices(request):
    rows = list(selectors.visible_devices(request.actor))
    for device in rows:
        device.online = selectors.is_online(device)
    return render(request, "devices/devices.html", {
        "devices": rows, "branches": _branches(request.actor),
        "can_manage": request.actor.can(permissions.MANAGE),
        "server": request.get_host()})


@permission_required(permissions.VIEW)
def device(request, pk):
    found = selectors.visible_devices(request.actor).filter(pk=pk).first()
    if found is None:
        raise Http404
    sync.expire_commands(found)
    found.online = selectors.is_online(found)
    users = list(DeviceUser.objects.filter(branch=found.branch).select_related("employee")
                 .order_by("removed", "pin"))
    return render(request, "devices/device.html", {
        "device": found, "users": users,
        "commands": found.commands.select_related("requested_by")[:10],
        "punches": found.punches.select_related("device_user__employee")[:RECENT],
        "employees": visible_employees(request.actor, permissions.MANAGE).filter(
            branch=found.branch, left_on__isnull=True).order_by("code"),
        "branches": _branches(request.actor),
        "can_manage": request.actor.can(permissions.MANAGE, branch=found.branch_id),
        "server": request.get_host()})
