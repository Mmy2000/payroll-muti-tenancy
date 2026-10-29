"""Bands and income tax, without the database."""

from decimal import Decimal as D

from apps.policies.domain.bands import Band, band_for, band_problems
from apps.policies.domain.tax import Bracket, bracket_problems, monthly_tax, yearly_tax

BANDS = [Band(1, 15, D("0.5")), Band(16, 30, D(1)), Band(31, 60, D(2))]


def test_the_band_holding_some_minutes():
    assert band_for(BANDS, 0) is None
    assert band_for(BANDS, 1).hours == D("0.5")
    assert band_for(BANDS, 15).hours == D("0.5")  # both ends included
    assert band_for(BANDS, 16).hours == D(1)
    assert band_for(BANDS, 61) is None


def test_band_problems():
    assert band_problems(BANDS) == {}
    assert band_problems([Band(10, 5, D(1))]) == {0: "reversed"}
    assert band_problems([Band(0, 10, D(-1))]) == {0: "negative"}
    # Order doesn't matter; the later-starting band of an overlapping pair is the one marked.
    assert band_problems([Band(20, 40, D(1)), Band(0, 20, D(1))]) == {0: "overlap"}


# The Egyptian brackets of 2023 (yearly): 0–40,000 at 0 %, then 10, 15, 20, 22.5, 25 %.
EGYPT = [Bracket(D(40000), D(0)), Bracket(D(55000), D(10)), Bracket(D(70000), D(15)),
         Bracket(D(200000), D(20)), Bracket(D(400000), D("22.5")), Bracket(None, D(25))]


def test_progressive_yearly_tax():
    assert yearly_tax(D(30000), EGYPT) == 0
    assert yearly_tax(D(55000), EGYPT) == D(1500)  # 15,000 at 10 %
    # 1,500 + 2,250 + 26,000 + 45,000 + 25 % of 100,000
    assert yearly_tax(D(500000), EGYPT) == D(99750)
    assert yearly_tax(D(-5), EGYPT) == 0


def test_income_above_a_closed_last_bracket_uses_its_rate():
    assert yearly_tax(D(150), [Bracket(D(100), D(10))]) == D(15)


def test_monthly_tax_is_the_yearly_tax_on_twelve_months_less_the_exemption():
    # 6,000 a month → 72,000 a year, less a 20,000 exemption → 52,000 → 1,200 a year.
    assert monthly_tax(D(6000), D(20000), EGYPT) == D(100)


def test_bracket_problems():
    assert bracket_problems(EGYPT) == {}
    assert bracket_problems([Bracket(None, D(10)), Bracket(D(5), D(10))]) == {0: "open_not_last"}
    assert bracket_problems([Bracket(D(10), D(10)), Bracket(D(10), D(20))]) == {1: "not_rising"}
    assert bracket_problems([Bracket(None, D(101))]) == {0: "rate"}
