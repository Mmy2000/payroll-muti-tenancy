"""Pay items already given."""

from __future__ import annotations

from datetime import date

from django.db.models import Q

from .models import AssignmentStatus, PayItemAssignment


def overlapping_assignments(employees, item, starts_on: date, ends_on: date | None):
    rows = PayItemAssignment.objects.filter(employee__in=employees, item=item,
                                            status=AssignmentStatus.ACTIVE)
    rows = rows.filter(Q(ends_on__isnull=True) | Q(ends_on__gte=starts_on))
    return rows if ends_on is None else rows.filter(starts_on__lte=ends_on)
