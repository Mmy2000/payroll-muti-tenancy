"""Periods, allocation and the engine, without the database."""

from datetime import date, timedelta
from decimal import Decimal as D

from apps.employees.domain.rates import PayTerms
from apps.payroll.domain import allocation
from apps.payroll.domain.engine import BLOCKING, calculate
from apps.payroll.domain.inputs import (
    OFF_CYCLE,
    REGULAR,
    Amount,
    Insurance,
    Lateness,
    Overtime,
    PayDay,
    PayslipInput,
    Tax,
)
from apps.payroll.domain.periods import Period, every, monthly
from apps.policies.domain.bands import Band
from apps.policies.domain.tax import Bracket

OCTOBER = Period(date(2026, 10, 1), date(2026, 10, 31))
SALARY = PayTerms("fixed", "monthly", D(6000), D(8))  # 200 a day, 25 an hour
ALL = frozenset({"attendance", "overtime", "lateness", "pay_items", "incentives", "penalties",
                 "advances", "loans", "insurance", "income_tax"})


# --- periods -------------------------------------------------------------------------------


def test_monthly_periods_with_a_start_day():
    assert monthly(date(2026, 10, 15)) == OCTOBER
    assert monthly(date(2026, 10, 15), 26) == Period(date(2026, 9, 26), date(2026, 10, 25))
    assert monthly(date(2026, 10, 26), 26) == Period(date(2026, 10, 26), date(2026, 11, 25))
    assert monthly(date(2027, 1, 5), 26) == Period(date(2026, 12, 26), date(2027, 1, 25))


def test_weekly_periods_from_an_anchor():
    anchor = date(2026, 1, 3)  # a Saturday
    week = every(date(2026, 10, 7), anchor, 7)
    assert week.start.weekday() == 5 and week.days == 7 and week.contains(date(2026, 10, 7))
    assert every(date(2025, 12, 30), anchor, 7) == Period(date(2025, 12, 27), date(2026, 1, 2))


# --- allocation ----------------------------------------------------------------------------


def test_a_monthly_item_split_between_weeks_adds_up_to_the_month():
    window = allocation.Window(date(2026, 1, 1), None)
    week = every(date(2026, 9, 26), date(2026, 1, 3), 7)
    total = D(0)
    for _ in range(7):  # the weeks covering October and some of its neighbours
        share = allocation.split_by_days(D(1000), week, window)
        october_part = allocation.split_by_days(
            D(1000), week, allocation.Window(date(2026, 10, 1), date(2026, 10, 31)))
        total += october_part
        assert share >= october_part
        week = every(week.end + timedelta(days=1), date(2026, 1, 3), 7)
    assert total == D(1000)


def test_whole_in_the_week_containing_the_first():
    window = allocation.Window(date(2026, 1, 1), None)
    first_week = every(date(2026, 10, 1), date(2026, 1, 3), 7)
    second_week = every(date(2026, 10, 8), date(2026, 1, 3), 7)
    assert allocation.whole_on_the_first(D(500), first_week, window) == D(500)
    assert allocation.whole_on_the_first(D(500), second_week, window) == D(0)


def test_same_unit_items_are_whole_or_prorated():
    rule = allocation.rule_for("monthly", "monthly")
    assert rule(D(300), OCTOBER, allocation.Window(date(2026, 1, 1), None)) == D(300)
    half = allocation.Window(date(2026, 10, 1), date(2026, 10, 15))
    assert rule(D(310), OCTOBER, half) == D(150)  # 15 of 31 days
    assert allocation.rule_for("weekly", "monthly")(
        D(70), OCTOBER, allocation.Window(date(2026, 1, 1), None)) == D(310)


# --- the engine ----------------------------------------------------------------------------


def _day(day, status="present", worked=480, **extra):
    values = {"terms": SALARY, "overtime_multiplier": D("1.5"), "absence_multiplier": D(1),
              "holiday_multiplier": D(1), "worked_minutes": worked if status == "present" else 0}
    values.update(extra)
    return PayDay(day=day, status=status, **values)


def _month(changes=None):
    """October, every day worked in full, with some days changed: {day of month: PayDay}."""
    days = {date(2026, 10, d): _day(date(2026, 10, d)) for d in range(1, 32)}
    for d, day in (changes or {}).items():
        days[date(2026, 10, d)] = day
    return tuple(days.values())


def _input(days=None, **extra):
    values = {"employee_id": 1, "employee_name": "A", "kind": REGULAR, "period": OCTOBER,
              "pay_frequency": "monthly", "employed": OCTOBER, "terms": SALARY,
              "features": ALL, "today": date(2026, 11, 2), "days": days or _month(),
              "attendance": True}
    values.update(extra)
    return PayslipInput(**values)


def _lines(result):
    return {line.code: line.amount for line in result.lines}


def test_a_full_month_is_the_salary_whatever_its_length():
    assert _lines(calculate(_input()))["salary"] == D(6000)
    february = Period(date(2026, 2, 1), date(2026, 2, 28))
    days = tuple(_day(february.start + timedelta(days=i)) for i in range(28))
    assert _lines(calculate(_input(days, period=february, employed=february)))["salary"] == D(6000)


def test_hired_mid_month_is_paid_by_the_day():
    employed = Period(date(2026, 10, 10), date(2026, 10, 31))
    days = tuple(d for d in _month() if d.day >= employed.start)
    assert _lines(calculate(_input(days, employed=employed)))["salary"] == D(22 * 200)


def test_absence_is_unpaid_and_penalized():
    days = _month({5: _day(date(2026, 10, 5), "absent", absence_multiplier=D(2)),
                     6: _day(date(2026, 10, 6), "excused")})
    lines = _lines(calculate(_input(days)))
    assert lines["days_not_paid"] == D(400)  # absent + excused, unpaid
    assert lines["absence_penalty"] == D(200)  # (2 − 1) day more, the absent day only


def test_holiday_work_overtime_and_missing_time():
    late = Lateness(10, (Band(11, 30, D("0.5")), Band(31, 60, D(1))))
    overtime = Overtime(15, ())
    days = _month({
        5: _day(date(2026, 10, 5), worked=480 + 70, overtime=overtime),  # 70 min over → 2 h
        6: _day(date(2026, 10, 6), worked=480 + 10, overtime=overtime),  # within "starts after"
        7: _day(date(2026, 10, 7), worked=420),  # 60 min short, no policy: 1 h deducted
        8: _day(date(2026, 10, 8), worked=440, late_minutes=40, lateness=late),  # band: 1 h
        9: _day(date(2026, 10, 9), worked=450, late_minutes=30, hourly_minutes=30,
                lateness=late),  # hourly leave covers it
        10: _day(date(2026, 10, 10), holiday=True, holiday_multiplier=D(2)),
    })
    lines = _lines(calculate(_input(days)))
    assert lines["overtime"] == D(2) * 25 * D("1.5")
    assert lines["missing_time"] == D(25) and lines["lateness"] == D(25)
    assert lines["holiday_work"] == D(200)


def test_a_marked_day_off_worked_is_all_overtime():
    days = _month({4: _day(date(2026, 10, 4), worked=180, rest_day=True, marked_day_off=True,
                             overtime=Overtime(0, ()))})
    assert _lines(calculate(_input(days)))["overtime"] == D(3) * 25 * D("1.5")


def test_amounts_follow_their_features():
    amounts = (
        Amount("item", "Transport", D(40), True, True, "x.Item", 1, per_day=True,
               start=date(2026, 10, 1), end=date(2026, 10, 10)),
        Amount("penalty", "Late", D(100), False, False, "x.Adj", 2),
        Amount("installment", "#1", D(500), False, False, "x.Inst", 3),
    )
    lines = calculate(_input(amounts=amounts)).lines
    transport = next(line for line in lines if line.code == "item")
    assert transport.amount == D(400) and transport.quantity == 10  # 10 days worked
    without_loans = calculate(_input(amounts=amounts, features=ALL - {"loans"}))
    assert "installment" not in _lines(without_loans)


def test_insurance_missing_blocks_and_zero_is_deliberate():
    assert calculate(_input(insured=True)).blocking == 1
    zero = calculate(_input(insured=True, insurance=Insurance(D(5000), D(0), D(0), 1)))
    assert zero.blocking == 0 and "insurance_employee" not in _lines(zero)
    real = calculate(_input(insured=True, insurance=Insurance(D(5000), D(11), D("18.75"), 1)))
    lines = _lines(real)
    assert lines["insurance_employee"] == D(550) and lines["insurance_employer"] == D("937.50")
    assert real.employer_cost == D("937.50")
    assert real.deductions == D(550)  # the employer's share is not taken from pay


def test_income_tax_annualized():
    brackets = (Bracket(D(40000), D(0)), Bracket(None, D(10)))
    tax = Tax(D(20000), brackets, 12, 1)
    lines = _lines(calculate(_input(tax=tax)))
    # 6000 × 12 − 20000 = 52000 → 12000 at 10 % = 1200 a year → 100 a month
    assert lines["income_tax"] == D(100)
    weekly = Period(date(2026, 10, 3), date(2026, 10, 9))
    weekly_pay = PayTerms("fixed", "weekly", D(1500), D(8))
    days = tuple(_day(weekly.start + timedelta(days=i), terms=weekly_pay) for i in range(7))
    result = calculate(_input(days, period=weekly, employed=weekly, pay_frequency="weekly",
                              terms=weekly_pay, tax=Tax(D(20000), brackets, 52, 1)))
    # 1500 × 52 − 20000 = 58000 → 18000 at 10 % = 1800 a year → 1800 / 52 a week
    assert _lines(result)["income_tax"] == D("34.62")


def test_daily_wage_needs_attendance_and_counts_paid_days():
    daily = PayTerms("daily", "monthly", D(250), D(8))
    days = tuple(_day(date(2026, 10, d), terms=daily) for d in range(1, 11)) + (
        _day(date(2026, 10, 11), "absent", terms=daily),
        _day(date(2026, 10, 12), "day_off", terms=daily, rest_day=True))
    period = Period(date(2026, 10, 1), date(2026, 10, 12))
    lines = _lines(calculate(_input(days, terms=daily, period=period, employed=period)))
    assert lines["day_wage"] == D(11 * 250)  # 10 worked + the paid day off
    blocked = calculate(_input(days, terms=daily, attendance=False))
    assert any(i.code == "needs_attendance" and i.severity == BLOCKING for i in blocked.issues)


def test_off_cycle_pays_only_dated_amounts():
    amounts = (Amount("incentive", "Bonus", D(1000), True, True, "x.Adj", 9),)
    result = calculate(_input(kind=OFF_CYCLE, days=(), amounts=amounts, insured=True,
                              tax=Tax(D(0), (Bracket(None, D(10)),), 12, 1)))
    assert _lines(result) == {"incentive": D(1000)}
    assert result.blocking == 0  # no insurance in an off-cycle run, so nothing missing


def test_negative_net_blocks_approval():
    amounts = (Amount("advance", "", D(9000), False, False, "x.Adv", 1),)
    assert calculate(_input(amounts=amounts)).blocking == 1
