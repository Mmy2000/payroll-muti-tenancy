"""Fingerprint device pages. They read and render; every save goes to the JSON API."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render

from apps.iam.authz import permission_required
from apps.org.selectors import branch_choices

from .. import permissions, selectors
from ..services import sync


def _branches(actor):
    return branch_choices(actor.branch_ids(permissions.MANAGE))


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
    found = selectors.find_device(request.actor, pk)
    if found is None:
        raise Http404
    sync.expire_commands(found)
    found.online = selectors.is_online(found)
    users = list(selectors.users_of_branch(found.branch))
    return render(request, "devices/device.html", {
        "device": found, "users": users,
        "commands": selectors.recent_commands(found),
        "punches": selectors.recent_punches(found),
        "employees": selectors.linkable_employees(request.actor, found.branch),
        "branches": _branches(request.actor),
        "can_manage": request.actor.can(permissions.MANAGE, branch=found.branch_id),
        "server": request.get_host()})
