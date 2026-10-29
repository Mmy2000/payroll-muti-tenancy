"""The day rules and work-day arithmetic, without the database."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from apps.attendance.domain.days import DayFacts, ManualEntry, Shift, Status, evaluate_day
from apps.attendance.domain.leave import Balance, leave_days, span_minutes
from apps.attendance.domain.summary import summarize
from apps.attendance.domain.workday import times_on, work_date_of

CAIRO = ZoneInfo("Africa/Cairo")
MONDAY = date(2026, 10, 5)
FRIDAY = date(2026, 10, 9)
DAY_SHIFT = Shift(time(9), time(17), frozenset({4}))


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=CAIRO)


def facts(day=MONDAY, **extra):
    return DayFacts(day=day, today=date(2026, 10, 28), tz=CAIRO, shift=DAY_SHIFT, **extra)


def test_a_clocked_day_measures_late_early_and_extra():
    result = evaluate_day(facts(punches=(at(MONDAY, 9, 20), at(MONDAY, 16, 50))))
    assert result.status == Status.PRESENT and result.source == "clock"
    assert (result.late_minutes, result.early_minutes, result.extra_minutes) == (20, 10, 0)
    assert result.worked_minutes == 450
    stayed = evaluate_day(facts(punches=(at(MONDAY, 8, 55), at(MONDAY, 18, 30))))
    assert (stayed.late_minutes, stayed.extra_minutes) == (0, 90)


def test_one_punch_is_a_missing_check_out():
    result = evaluate_day(facts(punches=(at(MONDAY, 9), at(MONDAY, 9, 0))))
    assert result.status == Status.PRESENT and result.missing_check_out
    assert result.worked_minutes == 0


def test_rules_in_order():
    assert evaluate_day(facts(employed=False)).status == Status.NOT_EMPLOYED
    assert evaluate_day(facts()).status == Status.ABSENT
    assert evaluate_day(facts(day=FRIDAY)).status == Status.DAY_OFF
    assert evaluate_day(facts(holiday="Armed Forces Day")).status == Status.HOLIDAY
    assert evaluate_day(facts(leave="Annual", holiday="X")).status == Status.LEAVE
    assert evaluate_day(facts(day=date(2026, 10, 28))).status == Status.UPCOMING  # today
    # A manager's entry wins over the clock and everything else.
    entry = ManualEntry("absent")
    clocked = (at(MONDAY, 9), at(MONDAY, 17))
    assert evaluate_day(facts(manual=entry, punches=clocked)).status == Status.ABSENT
    excused = evaluate_day(facts(manual=ManualEntry("excused")))
    assert excused.status == Status.EXCUSED and not excused.paid  # not penalized, not paid


def test_coming_on_a_day_marked_off_is_a_worked_rest_day():
    came = (at(MONDAY, 10), at(MONDAY, 13))
    result = evaluate_day(facts(manual=ManualEntry("day_off"), punches=came))
    assert result.status == Status.PRESENT and result.rest_day
    assert result.extra_minutes == 180 and result.late_minutes == 0
    assert evaluate_day(facts(manual=ManualEntry("day_off"))).status == Status.DAY_OFF


def test_coming_on_a_leave_day_keeps_the_leave():
    came = (at(MONDAY, 9), at(MONDAY, 17))
    result = evaluate_day(facts(leave="Annual leave", punches=came))
    assert result.status == Status.PRESENT and result.leave == "Annual leave"


def test_working_a_rest_day_is_all_extra():
    result = evaluate_day(facts(day=FRIDAY, punches=(at(FRIDAY, 10), at(FRIDAY, 14))))
    assert result.status == Status.PRESENT and result.rest_day
    assert result.extra_minutes == 240 and result.late_minutes == 0


def test_night_shift_work_day():
    night = Shift(time(22), time(6))
    # The day opens 4 hours before the shift: 18:00 to 18:00 the next day.
    assert work_date_of(at(MONDAY, 21, 55), night.starts_at, CAIRO) == MONDAY
    assert work_date_of(at(date(2026, 10, 6), 6, 10), night.starts_at, CAIRO) == MONDAY
    assert work_date_of(at(MONDAY, 17, 59), night.starts_at, CAIRO) == date(2026, 10, 4)
    result = evaluate_day(DayFacts(MONDAY, date(2026, 10, 28), CAIRO, shift=night,
                                   punches=(at(MONDAY, 22, 15), at(date(2026, 10, 6), 6, 30))))
    assert (result.late_minutes, result.extra_minutes, result.worked_minutes) == (15, 30, 495)


def test_times_typed_for_a_night_shift_end_the_next_day():
    start, end = times_on(MONDAY, time(22), time(6), CAIRO)
    assert end.date() == date(2026, 10, 6)


def test_leave_days_skip_days_off():
    working = lambda day: day.weekday() != 4  # noqa: E731
    assert leave_days(date(2026, 10, 5), date(2026, 10, 11), working) == 6
    assert span_minutes(time(23), time(1)) == 120
    balance = Balance(entitled=21, taken=15, requested=3)
    assert balance.remaining == 6 and balance.allows(6) and not balance.allows(7)


def test_summary():
    days = [evaluate_day(facts(punches=(at(MONDAY, 9, 10), at(MONDAY, 17)))),
            evaluate_day(facts()), evaluate_day(facts(day=FRIDAY))]
    summary = summarize(days)
    assert summary.days(Status.PRESENT) == 1 and summary.days(Status.ABSENT) == 1
    assert summary.late_minutes == 10 and summary.worked_minutes == 470
