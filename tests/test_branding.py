"""Branding (platform settings, client logos) and uploaded files kept apart per client."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.tenancy import tenant_context
from conftest import login

pytestmark = pytest.mark.django_db
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def png(name="logo.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def _profile(tenant):
    from apps.org.models import TenantProfile

    with tenant_context(tenant.id):
        return TenantProfile.objects.get()


def test_client_uploads_its_logo_into_its_own_folder(tenant_a, media):
    client = login(tenant_a)
    client.cookies["django_language"] = "en"
    page = client.get("/settings/company/")
    assert page.status_code == 200 and "Company" in page.content.decode()
    response = client.post("/settings/company/", {
        "display_name": "Alpha Gold", "accent": "blue", "logo": png()})
    assert response.status_code == 302
    profile = _profile(tenant_a)
    assert profile.logo.name.startswith(f"tenants/{tenant_a.id}/branding/")
    assert (profile.display_name, profile.accent) == ("Alpha Gold", "blue")
    first = profile.logo.name
    assert (media / first).exists()

    html = client.get("/").content.decode()
    assert f"/media/{first}" in html  # sidebar and browser tab

    # Replacing deletes the old file; removing clears it.
    client.post("/settings/company/", {"display_name": "Alpha Gold", "accent": "blue",
                                       "logo": png("new.png")})
    assert not (media / first).exists()
    client.post("/settings/company/", {"display_name": "Alpha Gold", "accent": "blue",
                                       "logo-clear": "on"})
    assert not _profile(tenant_a).logo


def test_only_images_are_accepted(tenant_a):
    client = login(tenant_a)
    client.cookies["django_language"] = "en"
    svg = SimpleUploadedFile("logo.svg", b"<svg onload='alert(1)'/>", content_type="image/svg+xml")
    page = client.post("/settings/company/", {"display_name": "A", "accent": "gold", "logo": svg})
    assert page.status_code == 200 and "Upload a PNG, JPEG" in page.content.decode()
    fake = SimpleUploadedFile("logo.png", b"not really a png", content_type="image/png")
    page = client.post("/settings/company/", {"display_name": "A", "accent": "gold", "logo": fake})
    assert "Upload a PNG, JPEG" in page.content.decode()
    assert not _profile(tenant_a).logo


def test_company_page_needs_the_permission(tenant_a, make_member):
    make_member(tenant_a, "clerk", "viewer")
    assert login(tenant_a, username="clerk").get("/settings/company/").status_code == 403
