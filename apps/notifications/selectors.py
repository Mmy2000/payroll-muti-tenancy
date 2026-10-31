"""What is waiting for the member (the bell's "Needs attention", and the dashboard): each queue
only for those who may act on it, counted in the branches where they may.

Each entry: (permission, label, icon, url, count function(actor) → int).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Notification


def _pending(model, permission):
    def count(actor):
        from apps.attendance.models import RequestStatus
        from apps.employees.selectors import visible_employees

        return model.objects.filter(status=RequestStatus.PENDING,
                                    employee__in=visible_employees(actor, permission)).count()
    return count


def _leave(actor):
    from apps.attendance.models import LeaveRequest

    return _pending(LeaveRequest, "attendance.leave.approve")(actor)


def _hourly(actor):
    from apps.attendance.models import HourlyLeave

    return _pending(HourlyLeave, "attendance.hourly.approve")(actor)


def _drafts(kind):
    def count(actor):
        from apps.adjustments.models import BatchStatus
        from apps.adjustments.selectors import visible_batches

        return visible_batches(actor, kind).filter(status=BatchStatus.DRAFT).count()
    return count


def _runs(actor):
    from apps.payroll.models import RunStatus
    from apps.payroll.selectors import visible_runs

    return visible_runs(actor).filter(status=RunStatus.DRAFT).count()


def _quiet_devices(actor):
    from apps.devices.selectors import visible_devices

    since = timezone.now() - timedelta(days=1)
    return visible_devices(actor).filter(is_active=True).exclude(last_seen_at__gte=since).count()


@dataclass(frozen=True)
class Queue:
    permission: str
    label: object
    icon: str
    url_name: str
    count: object
    query: str = ""


QUEUES = [
    Queue("attendance.leave.approve", _("Leave to decide"), "calendar-days", "leave-requests",
          _leave),
    Queue("attendance.hourly.approve", _("Hourly leave to decide"), "calendar-clock",
          "hourly-leave", _hourly),
    Queue("adjustments.incentive.approve", _("Incentives to approve"), "award", "incentives",
          _drafts("incentive"), "?status=draft"),
    Queue("adjustments.penalty.approve", _("Penalties to approve"), "gavel", "penalties",
          _drafts("penalty"), "?status=draft"),
    Queue("payroll.run.approve", _("Payroll runs to approve"), "calculator", "payroll-runs",
          _runs),
    Queue("devices.device.manage", _("Devices not calling for a day"), "fingerprint", "devices",
          _quiet_devices),
]


def waiting(actor) -> list[dict]:
    """[{label, icon, url, count}] of the queues with something in them."""
    found = []
    for queue in QUEUES:
        if not actor.can(queue.permission):
            continue
        count = queue.count(actor)
        if count:
            found.append({"label": str(queue.label), "icon": queue.icon,
                          "url": reverse(queue.url_name) + queue.query, "count": count})
    return found


ICONS = sorted({"bell", *(q.icon for q in QUEUES)})


def for_member(member) -> QuerySet:
    return Notification.objects.filter(member=member)


def newest_for(member, *, unread_only: bool = False, before: int | None = None) -> QuerySet:
    """Newest first; `before`: those older than that id."""
    rows = for_member(member)
    if unread_only:
        rows = rows.filter(read_at__isnull=True)
    if before is not None:
        rows = rows.filter(pk__lt=before)
    return rows.order_by("-id")


def unread_count(member) -> int:
    return for_member(member).filter(read_at__isnull=True).count()
