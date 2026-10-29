"""Plans kept in the database and managed from the console."""


import pytest

from apps.platform.tenants import features
from apps.platform.tenants.models import Plan, PlanFeature

pytestmark = pytest.mark.django_db


def _plan_data(**overrides):
    data = {"code": "gold-plus", "name": "Gold Plus", "name_ar": "جولد بلس",
            "description": "For big shops", "price": "1500", "currency": "EGP",
            "billing_period": "monthly", "max_branches": "5", "max_users": "20",
            "requests_per_minute": "900", "trial_days": "", "position": "5",
            "is_active": "on"}
    data.update({f"feature_{f.key}": "on" for f in features.FEATURES
                 if f.key not in ("manufacturing", "wholesale")})
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_a_database_without_plans_still_creates_clients(make_tenant):
    PlanFeature.objects.all().delete()
    Plan.objects.all().delete()
    tenant = make_tenant("fresh")
    assert tenant.plan_id == "standard"
    assert Plan.objects.count() == 4
