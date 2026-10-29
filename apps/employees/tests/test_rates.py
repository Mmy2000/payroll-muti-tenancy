from decimal import Decimal as D

from apps.employees.domain.rates import PayTerms


def test_a_month_counts_as_thirty_days():
    terms = PayTerms("fixed", "monthly", D(6000), D(8))
    assert (terms.daily, terms.hourly, terms.monthly) == (D(200), D(25), D(6000))


def test_weekly_and_biweekly_salaries_count_their_own_days():
    assert PayTerms("fixed", "weekly", D(1400), D(8)).daily == D(200)
    assert PayTerms("fixed", "biweekly", D(2800), D(8)).daily == D(200)
    assert PayTerms("fixed", "weekly", D(1400), D(8)).monthly == D(6000)


def test_daily_and_hourly_wages():
    daily = PayTerms("daily", "weekly", D(250), D(10))  # a daily wage, paid every week
    assert (daily.daily, daily.hourly, daily.monthly) == (D(250), D(25), D(7500))
    hourly = PayTerms("hourly", "monthly", D(30), D(8))
    assert (hourly.daily, hourly.hourly) == (D(240), D(30))
