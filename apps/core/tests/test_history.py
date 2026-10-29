"""Effective-dated values: the row in effect on a day, and the spans of a period."""

from datetime import date
from decimal import Decimal

import pytest

from apps.core.history import in_effect, spans
from apps.core.tenancy import tenant_context
from apps.policies.models import InsuranceRate

pytestmark = pytest.mark.django_db


def _rates():
    for day, rate in ((date(2025, 1, 1), 11), (date(2025, 7, 1), 12), (date(2026, 1, 1), 13)):
        InsuranceRate.objects.create(effective_from=day, employee_rate=Decimal(rate),
                                     employer_rate=Decimal(18))


def test_the_row_in_effect_on_a_day(tenant_a):
    with tenant_context(tenant_a.id):
        _rates()
        rates = InsuranceRate.objects.all()
        assert in_effect(rates, date(2024, 12, 31)) is None
        assert in_effect(rates, date(2025, 1, 1)).employee_rate == 11
        assert in_effect(rates, date(2025, 6, 30)).employee_rate == 11
        assert in_effect(rates, date(2025, 7, 1)).employee_rate == 12
        assert in_effect(rates, date(2030, 1, 1)).employee_rate == 13


def test_spans_cut_a_period_into_the_rows_covering_it(tenant_a):
    with tenant_context(tenant_a.id):
        _rates()
        found = spans(InsuranceRate.objects.all(), date(2025, 6, 15), date(2025, 7, 14))
        assert [(s.row.employee_rate, s.start, s.end) for s in found] == [
            (11, date(2025, 6, 15), date(2025, 6, 30)),
            (12, date(2025, 7, 1), date(2025, 7, 14)),
        ]
        # Days before the first row are not covered.
        early = spans(InsuranceRate.objects.all(), date(2024, 12, 20), date(2025, 1, 10))
        assert [(s.start, s.end) for s in early] == [(date(2025, 1, 1), date(2025, 1, 10))]
