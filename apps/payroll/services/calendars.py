"""Pay calendars: how a frequency divides the year into periods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.errors import DomainError, invalid_fields

from ..domain import periods as period_rules
from ..domain.periods import Period
from ..models import LIVE, Frequency, MonthlyRule, PayCalendar, PayrollRun, PeriodKind, ScopeKind
from ..permissions import SETUP
from ..validators import require_scope

DEFAULT_ANCHOR = date(2026, 1, 3)  # a Saturday: weeks run Saturday to Friday until changed


def calendar_for(frequency: str) -> PayCalendar:
    calendar, _created = PayCalendar.objects.get_or_create(
        frequency=frequency,
        defaults={"anchor": None if frequency == Frequency.MONTHLY else DEFAULT_ANCHOR})
    return calendar


@dataclass(frozen=True)
class CalendarInput:
    frequency: str
    start_day: int = 1
    anchor: date | None = None
    monthly_items: str = MonthlyRule.SPLIT


def save_calendar(data: CalendarInput, *, actor=None) -> PayCalendar:
    """Change how a frequency's periods fall; refused once runs of it exist, as their periods
    would no longer line up. Calendars are the whole company's: every branch is needed."""
    require_scope(actor, SETUP, ScopeKind.ALL, None)
    errors = {}
    if data.frequency not in Frequency.values:
        errors["frequency"] = [_("Choose a pay frequency.")]
    elif data.frequency == Frequency.MONTHLY and not 1 <= data.start_day <= 28:
        errors["start_day"] = [_("Choose a day from 1 to 28.")]
    elif data.frequency != Frequency.MONTHLY and data.anchor is None:
        errors["anchor"] = [_("Enter the first day of one pay period.")]
    if data.monthly_items not in MonthlyRule.values:
        errors["monthly_items"] = [_("Choose from the list.")]
    if errors:
        raise invalid_fields(errors)
    with transaction.atomic():
        calendar = PayCalendar.objects.select_for_update().filter(pk=calendar_for(
            data.frequency).pk).get()
        moved = (calendar.start_day != data.start_day or calendar.anchor != data.anchor)
        if moved and PayrollRun.objects.filter(period__frequency=data.frequency,
                                               period__kind=PeriodKind.REGULAR,
                                               status__in=LIVE).exists():
            raise DomainError(_("Runs already exist for this pay frequency: its periods can't "
                                "move any more."), code="PAYROLL_CALENDAR_IN_USE")
        calendar.start_day = data.start_day if data.frequency == Frequency.MONTHLY else 1
        calendar.anchor = data.anchor if data.frequency != Frequency.MONTHLY else None
        calendar.monthly_items = data.monthly_items
        calendar.updated_by = getattr(actor, "user", None)
        calendar.save()
    return calendar


def period_on(frequency: str, day: date) -> Period:
    calendar = calendar_for(frequency)
    return period_rules.period_containing(day, frequency, start_day=calendar.start_day,
                                          anchor=calendar.anchor)
