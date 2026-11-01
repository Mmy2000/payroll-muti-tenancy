"""The branch form places a branch on a map, and still sends the same plain fields."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import translation

from apps.core.tenancy import tenant_context
from apps.org.models import Branch
from conftest import login

pytestmark = pytest.mark.django_db


def _page(client, tenant, name, *args):
    return client.get(reverse(name, args=args), HTTP_HOST=f"{tenant.slug}.localhost")


def test_the_form_has_the_map_and_the_fields_it_sends(tenant_a):
    html = _page(login(tenant_a, language="en"), tenant_a, "branch-new").content.decode()
    assert "data-location-picker" in html and "vendor/leaflet/leaflet.js" in html
    for field in ('name="latitude"', 'name="longitude"', 'name="radius_m"'):
        assert field in html


def test_saved_coordinates_stay_plain_numbers_in_arabic(tenant_a):
    with tenant_context(tenant_a.id):
        branch = Branch.objects.get(code=1)
        branch.latitude, branch.longitude = Decimal("30.044420"), Decimal("31.235712")
        branch.radius_m = 350
        branch.save()
    with translation.override("ar"):
        client = login(tenant_a, language="ar")
        html = _page(client, tenant_a, "branch-edit", branch.pk).content.decode()
    assert 'value="30.044420"' in html and 'value="31.235712"' in html and 'value="350"' in html
