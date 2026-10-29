from decimal import Decimal as D

from apps.employees.domain.rates import daily_rate, hourly_rate


def test_a_month_counts_as_thirty_days():
    assert daily_rate("monthly", D(6000)) == D(200)
    assert hourly_rate("monthly", D(6000), D(8)) == D(25)


def test_daily_and_weekly_wages():
    assert daily_rate("daily", D(250)) == D(250)
    assert daily_rate("weekly", D(1400)) == D(200)  # provisional: 7 paid days (open question)
    assert hourly_rate("daily", D(250), D(10)) == D(25)
