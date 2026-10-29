"""How attendance looks on screen: a day's status as a badge, minutes as hours."""

from django import template
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.attendance.domain.days import Status
from apps.attendance.models import RequestStatus

register = template.Library()

STATUS = {  # status → (label, badge class)
    Status.PRESENT: (_("Present"), "badge-success"),
    Status.ABSENT: (_("Absent"), "badge-danger"),
    Status.EXCUSED: (_("Excused"), "badge-brand"),
    Status.DAY_OFF: (_("Day off"), "badge-neutral"),
    Status.HOLIDAY: (_("Holiday"), "badge-neutral"),
    Status.LEAVE: (_("Leave"), "badge-brand"),
    Status.UPCOMING: (_("Not yet"), "badge-neutral"),
    Status.NOT_EMPLOYED: (_("Not employed"), "badge-neutral"),
}
# The entry that matches a day the manager entered; anything else is corrected to "worked".
ENTRY_KIND = {Status.PRESENT: "worked", Status.ABSENT: "absent", Status.EXCUSED: "excused",
              Status.DAY_OFF: "day_off"}
REQUEST_BADGES = {RequestStatus.PENDING: "badge-warning", RequestStatus.APPROVED: "badge-success",
                  RequestStatus.REJECTED: "badge-danger", RequestStatus.CANCELLED: "badge-neutral"}


@register.simple_tag
def day_badge(result) -> str:
    label, css = STATUS[result.status]
    if result.label and result.status in (Status.LEAVE, Status.HOLIDAY):
        label = result.label
    return format_html('<span class="badge {}"><span class="badge-dot"></span>{}</span>',
                       css, label)


@register.simple_tag
def request_badge(request) -> str:
    return format_html('<span class="badge {}">{}</span>', REQUEST_BADGES[request.status],
                       request.get_status_display())


@register.filter
def entry_kind(result) -> str:
    """The kind to preselect when correcting a day."""
    return ENTRY_KIND.get(result.status, "worked") if result.source == "manual" else "worked"


@register.filter
def hours(minutes) -> str:
    """125 → "2:05"; 0 → "—"."""
    if not minutes:
        return "—"
    return f"{minutes // 60}:{minutes % 60:02d}"
