"""Which work day a moment belongs to, and when a day's shift starts and ends. Pure: no database.

A work day opens 4 hours before the shift starts and lasts 24 hours (PayRole:
Enp/salary_base.py, WORKDAY_LEAD_HOURS). So for a 22:00–06:00 night shift the day runs from 18:00
to 18:00 the next day, and the 06:00 check-out belongs to the day the shift began.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo

LEAD = timedelta(hours=4)


def shift_bounds(day: date, starts_at: time, ends_at: time,
                 tz: tzinfo) -> tuple[datetime, datetime]:
    """The shift of `day`, as aware datetimes; one ending at or before its start ends the next
    day."""
    start = datetime.combine(day, starts_at, tzinfo=tz)
    end = datetime.combine(day, ends_at, tzinfo=tz)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def work_date_of(moment: datetime, starts_at: time, tz: tzinfo) -> date:
    """The work day a moment belongs to, for a shift starting at `starts_at`."""
    local = moment.astimezone(tz).replace(tzinfo=None)
    offset = timedelta(hours=starts_at.hour, minutes=starts_at.minute) - LEAD
    return (local - offset).date()


def times_on(day: date, check_in: time, check_out: time | None,
             tz: tzinfo) -> tuple[datetime, datetime | None]:
    """A check-in and check-out typed as times for `day`: a check-out at or before the
    check-in is on the next day (a night shift)."""
    start = datetime.combine(day, check_in, tzinfo=tz)
    if check_out is None:
        return start, None
    end = datetime.combine(day, check_out, tzinfo=tz)
    if end <= start:
        end += timedelta(days=1)
    return start, end
