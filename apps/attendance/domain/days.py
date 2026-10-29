"""What one employee's work day was: present, absent, a day off… and, when they worked, how late,
how early and how long. Pure: no database. The screens and payroll both call `evaluate_day`.

The status is decided by the first rule that applies (chain of responsibility):

1. not employed that day (before hiring, after leaving);
2. a manager's entry for the day (it wins over everything else, except that a day marked
   "day off" on which the employee clocked in is a worked rest day: all of it is extra, as
   PayRole's Salary/payroll.py treats a day marked weekly off);
3. the clock: any punch makes the day "present", even on a rest day (then all of it is extra)
   or on approved leave (then `leave` keeps the leave's name: payroll pays such a day at the
   holiday rate and doesn't count it as leave taken);
4. approved leave;
5. a public holiday;
6. a weekly day off;
7. a day still to come (today included, until there is a punch);
8. otherwise absent.

Late, early and extra minutes are measured against the shift, as they are; grace minutes and
bands are payroll's business (apps.policies).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum

from .workday import shift_bounds

SAME_PUNCH = timedelta(seconds=60)  # a second punch closer than this is the same one


class Status(StrEnum):
    NOT_EMPLOYED = "not_employed"
    UPCOMING = "upcoming"
    PRESENT = "present"
    ABSENT = "absent"
    EXCUSED = "excused"
    DAY_OFF = "day_off"
    HOLIDAY = "holiday"
    LEAVE = "leave"


@dataclass(frozen=True)
class Shift:
    starts_at: time
    ends_at: time
    days_off: frozenset[int] = frozenset()  # date.weekday() numbers
    early_leave_minutes: int = 0


@dataclass(frozen=True)
class ManualEntry:
    kind: str  # apps.attendance.models.DayKind
    check_in: datetime | None = None
    check_out: datetime | None = None


@dataclass(frozen=True)
class DayFacts:
    day: date
    today: date
    tz: tzinfo
    employed: bool = True
    shift: Shift | None = None
    holiday: str = ""  # the holiday's name
    leave: str = ""  # the approved leave's type name
    leave_paid: bool = True
    manual: ManualEntry | None = None
    punches: tuple[datetime, ...] = ()
    hourly_minutes: int = 0  # approved hourly leave

    @property
    def weekly_off(self) -> bool:
        return self.shift is not None and self.day.weekday() in self.shift.days_off

    @property
    def marked_day_off(self) -> bool:
        return self.manual is not None and self.manual.kind == "day_off"

    @property
    def rest_day(self) -> bool:
        return bool(self.holiday) or self.weekly_off or self.marked_day_off


@dataclass(frozen=True)
class DayResult:
    day: date
    status: Status
    source: str = ""  # "manual" or "clock" when the status comes from one of them
    label: str = ""  # the leave type or holiday name
    leave: str = ""  # approved leave covering the day, even when the employee came
    marked_day_off: bool = False  # a manager marked it a day off (worked anyway: all extra)
    holiday: str = ""  # the public holiday on the day, even when the employee came
    paid: bool = True  # an absence that is still paid (excused, paid leave, holiday, day off)
    rest_day: bool = False
    check_in: datetime | None = None
    check_out: datetime | None = None
    worked_minutes: int = 0
    late_minutes: int = 0
    early_minutes: int = 0
    extra_minutes: int = 0
    missing_check_out: bool = False
    hourly_minutes: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def _minutes(delta: timedelta) -> int:
    return max(int(delta.total_seconds() // 60), 0)


def presence(facts: DayFacts, check_in: datetime, check_out: datetime | None,
             source: str) -> DayResult:
    """A day the employee came: their times measured against the shift."""
    result = DayResult(facts.day, Status.PRESENT, source=source, rest_day=facts.rest_day,
                       check_in=check_in, check_out=check_out,
                       missing_check_out=check_out is None, hourly_minutes=facts.hourly_minutes,
                       label=facts.holiday or facts.leave, leave=facts.leave,
                       holiday=facts.holiday, marked_day_off=facts.marked_day_off)
    if check_out is None:
        return result
    worked = _minutes(check_out - check_in)
    if facts.shift is None or facts.rest_day:
        return replace(result, worked_minutes=worked, extra_minutes=worked)
    start, end = shift_bounds(facts.day, facts.shift.starts_at, facts.shift.ends_at, facts.tz)
    return replace(result, worked_minutes=worked, late_minutes=_minutes(check_in - start),
                   early_minutes=_minutes(end - check_out),
                   extra_minutes=_minutes(check_out - end))


def pair(punches: tuple[datetime, ...]) -> tuple[datetime, datetime | None] | None:
    """The first and last punch of a day (PayRole: zkk/zk_attendance.py sync_days)."""
    if not punches:
        return None
    first, last = min(punches), max(punches)
    return first, (last if last - first >= SAME_PUNCH else None)


# --- the rules, in order -------------------------------------------------------------------

Rule = Callable[[DayFacts], DayResult | None]


def not_employed(facts: DayFacts) -> DayResult | None:
    return None if facts.employed else DayResult(facts.day, Status.NOT_EMPLOYED, paid=False)


def manual_entry(facts: DayFacts) -> DayResult | None:
    entry = facts.manual
    if entry is None:
        return None
    if entry.kind == "worked":
        return presence(facts, entry.check_in, entry.check_out, "manual")
    if entry.kind == "day_off" and facts.punches:
        return None  # they came anyway: the clock decides, on a rest day
    status = {"absent": Status.ABSENT, "excused": Status.EXCUSED,
              "day_off": Status.DAY_OFF}[entry.kind]
    # An excused absence (PayRole: a day marked "إجازة بإذن") is not penalized, and not paid
    # either: paid days away are leave of a paid type.
    return DayResult(facts.day, status, source="manual", paid=status == Status.DAY_OFF,
                     rest_day=status == Status.DAY_OFF)


def clocked(facts: DayFacts) -> DayResult | None:
    times = pair(facts.punches)
    return None if times is None else presence(facts, *times, "clock")


def on_leave(facts: DayFacts) -> DayResult | None:
    if not facts.leave:
        return None
    return DayResult(facts.day, Status.LEAVE, label=facts.leave, leave=facts.leave,
                     paid=facts.leave_paid, rest_day=facts.rest_day)


def holiday(facts: DayFacts) -> DayResult | None:
    return (DayResult(facts.day, Status.HOLIDAY, label=facts.holiday, holiday=facts.holiday,
                      rest_day=True) if facts.holiday else None)


def weekly_off(facts: DayFacts) -> DayResult | None:
    return DayResult(facts.day, Status.DAY_OFF, rest_day=True) if facts.weekly_off else None


def not_yet(facts: DayFacts) -> DayResult | None:
    return DayResult(facts.day, Status.UPCOMING) if facts.day >= facts.today else None


def absent(facts: DayFacts) -> DayResult:
    return DayResult(facts.day, Status.ABSENT, paid=False,
                     hourly_minutes=facts.hourly_minutes)


RULES: tuple[Rule, ...] = (not_employed, manual_entry, clocked, on_leave, holiday, weekly_off,
                           not_yet, absent)


def evaluate_day(facts: DayFacts) -> DayResult:
    for rule in RULES:
        result = rule(facts)
        if result is not None:
            return result
    raise AssertionError("the last rule always decides")  # pragma: no cover
