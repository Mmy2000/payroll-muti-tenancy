"""The endpoints a fingerprint device calls (ZKTeco ADMS: apps/devices/protocol.py), on the
client's own address, as PayRole served them: `/iclock/cdata`, `/iclock/getrequest`,
`/iclock/devicecmd`, no trailing slash, plain text.

The client is the host's, as for every request; the device must be one of its active devices
(by serial), and the client must have devices switched on. Anything else is refused the way
PayRole did ("UNKNOWN DEVICE", 403), so a device gets no hint of what exists elsewhere. There is
no session, no login and no CSRF token: the device can't send them.
"""

from __future__ import annotations

import logging
from functools import wraps

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.iam.signals import client_ip
from apps.platform.tenants import features

from . import protocol, selectors, services

logger = logging.getLogger(__name__)
FEATURE = "zk_devices"


def _text(body: str, status: int = 200) -> HttpResponse:
    return HttpResponse(body, status=status, content_type="text/plain; charset=utf-8")


def _body(request) -> str:
    return request.body.decode("utf-8", errors="replace")


def device_call(view):
    """Find the calling device (locked for the call) or refuse it."""
    @csrf_exempt
    @wraps(view)
    def wrapped(request):
        tenant = getattr(request, "tenant", None)
        device = None
        if tenant is not None and features.is_enabled(tenant.id, FEATURE):
            device = selectors.device_for(request.GET.get("SN", ""))
        if device is None:
            logger.warning("refused device call %s SN=%r", request.path,
                           request.GET.get("SN", "")[:40])
            return _text("UNKNOWN DEVICE\n", status=403)
        services.seen(device, ip=client_ip(request), info=request.GET.get("INFO", ""))
        return view(request, device)

    return wrapped


@device_call
def cdata(request, device):
    if request.method == "GET":
        return _text(services.handshake(device))
    table = request.GET.get("table", "").upper()
    if table == "ATTLOG":
        count = services.receive_punches(device, protocol.parse_attlog(_body(request)))
    elif table in ("OPERLOG", "USERINFO"):
        count = services.receive_users(device, protocol.parse_users(_body(request)))
    else:
        count = 0
    return _text(f"OK: {count}\n")


@device_call
def getrequest(request, device):
    return _text(protocol.command_lines(services.next_commands(device)))


@device_call
def devicecmd(request, device):
    services.record_replies(device, protocol.parse_replies(_body(request)))
    return _text("OK\n")
