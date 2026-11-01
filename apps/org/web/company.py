"""Company settings inside the workspace: the client's own name on screens, logo and colour."""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.media import ImageUploadInput, validate_image
from apps.core.paging import PAGE_SIZE_CHOICES
from apps.iam.authz import permission_required

from .. import selectors, services
from ..appearance import ACCENT_CHOICES

QR_MOST_MINUTES = 7 * 24 * 60


class CompanyForm(forms.Form):
    display_name = forms.CharField(label=_("Name on screens and receipts"), max_length=200,
                                   widget=forms.TextInput(attrs={"class": "form-input"}))
    accent = forms.ChoiceField(
        label=_("Accent colour"), choices=ACCENT_CHOICES,
        widget=forms.Select(attrs={"class": "form-input"}),
        help_text=_("Users can still pick their own in the appearance menu."))
    logo = forms.FileField(
        label=_("Logo"), required=False, validators=[validate_image],
        widget=ImageUploadInput(attrs={"class": "form-file"}),
        help_text=_("PNG, JPEG, WEBP, GIF or ICO, up to 2 MB. A square or wide image on a "
                    "transparent background works best."))
    page_size = forms.TypedChoiceField(
        label=_("Rows on each page of a list"), choices=PAGE_SIZE_CHOICES, coerce=int,
        required=False, empty_value=None,
        widget=forms.Select(attrs={"class": "form-input"}),
        help_text=_("For every list and report on screen, for everyone in the company. Prints and "
                    "exports always include every row."))
    app_qr_minutes = forms.IntegerField(
        label=_("A sign-in QR works for (minutes)"), min_value=1, max_value=QR_MOST_MINUTES,
        widget=forms.NumberInput(attrs={"class": "form-input num w-full text-start"}),
        help_text=_("From 1 minute to 1 week (10080). Shorter is safer: a QR signs in whoever "
                    "scans it first."))


@permission_required("org.settings.manage")
def company(request):
    profile = selectors.tenant_profile()
    form = CompanyForm(request.POST or None, request.FILES or None, initial={
        "display_name": profile.display_name, "accent": profile.accent,
        "logo": profile.logo or None, "app_qr_minutes": profile.app_qr_minutes,
        "page_size": profile.page_size})
    uses_the_app = request.actor.can("mobile.qr.manage")
    if not uses_the_app:
        del form.fields["app_qr_minutes"]
    if request.method == "POST" and form.is_valid():
        services.save_company(
            profile, display_name=form.cleaned_data["display_name"],
            accent=form.cleaned_data["accent"], logo=form.cleaned_data["logo"],
            page_size=form.cleaned_data["page_size"],
            app_qr_minutes=form.cleaned_data["app_qr_minutes"] if uses_the_app else None)
        messages.success(request, _("Saved."))
        return redirect("company")
    return render(request, "org/company.html", {
        "form": form, "profile": profile,
        "logo_url": profile.logo.url if profile.logo else ""})
