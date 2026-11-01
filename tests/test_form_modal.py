"""Create and edit pages open in the modal from every link to them, and stay pages of their own."""

import re
from pathlib import Path

import pytest
from django.urls import reverse

from conftest import login

ROOT = Path(__file__).resolve().parent.parent
FORM_LINK = re.compile(r"<a\b[^>]*href=\"\{% url [^%]*-(?:new|edit)['\s][^>]*>")


def _templates():
    for folder in ("apps", "templates"):
        for path in (ROOT / folder).rglob("*.html"):
            if "console" not in path.parts:  # the platform console posts classic forms
                yield path


def test_every_link_to_a_create_or_edit_page_opens_the_modal():
    forgotten = [f"{path.relative_to(ROOT)}: {link[:70]}" for path in _templates()
                 for link in FORM_LINK.findall(path.read_text(encoding="utf-8"))
                 if "data-form-modal" not in link]
    assert forgotten == []


@pytest.mark.django_db
def test_a_form_page_stays_a_page_and_the_modal_is_on_every_page(tenant_a):
    client = login(tenant_a, language="en")
    response = client.get(reverse("position-new"), HTTP_HOST=f"{tenant_a.slug}.localhost")
    page = response.content.decode()
    assert response.status_code == 200
    assert "<main" in page and "data-api-form" in page and "data-modal-form" in page
