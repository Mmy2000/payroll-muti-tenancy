"""The pay items, and those already given."""

from __future__ import annotations

from datetime import date

from django.db.models import Max, Q

from apps.employees.selectors import employee_rows

from .models import AssignmentStatus, PayItem, PayItemAssignment
from .permissions import ENTRY_VIEW


def pay_items():
    return PayItem.objects.order_by("code")


def active_pay_items():
    return PayItem.objects.filter(is_active=True)


def find_pay_item(pk: int) -> PayItem | None:
    return PayItem.objects.filter(pk=pk).first()


def pay_item_choices() -> list[tuple[int, str]]:
    return list(PayItem.objects.values_list("pk", "name"))


def next_pay_item_code() -> int:
    return (PayItem.objects.aggregate(top=Max("code"))["top"] or 0) + 1


def by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


def assignments_running(actor, first: date, last: date):
    """The items running on any day from `first` to `last`, for the employees the actor may
    see."""
    running = PayItemAssignment.objects.filter(Q(ends_on__isnull=True) | Q(ends_on__gte=first),
                                               starts_on__lte=last)
    return (employee_rows(running, actor, ENTRY_VIEW, ("employee", "item"))
            .order_by("employee__code", "item__code"))


def overlapping_assignments(employees, item, starts_on: date, ends_on: date | None):
    rows = PayItemAssignment.objects.filter(employee__in=employees, item=item,
                                            status=AssignmentStatus.ACTIVE)
    rows = rows.filter(Q(ends_on__isnull=True) | Q(ends_on__gte=starts_on))
    return rows if ends_on is None else rows.filter(starts_on__lte=ends_on)
