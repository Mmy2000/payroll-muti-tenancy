"""Reading the policies: the lists their screens show, and one policy."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.core.errors import NotFound

from .models import InsuranceRate, PublicHoliday, TaxTable


def get_record(model, pk: int):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound(_("Not found."))
    return obj


def banded_policies(model):
    return model.objects.prefetch_related("bands")


def listed_banded_policies(model):
    return banded_policies(model).order_by("-is_active", "name")


def find_banded_policy(model, pk):
    return banded_policies(model).filter(pk=pk).first()


def tax_tables():
    return TaxTable.objects.prefetch_related("brackets")


def listed_tax_tables():
    return tax_tables().order_by("-effective_from")


def find_tax_table(pk):
    return tax_tables().filter(pk=pk).first()


def insurance_rates():
    return InsuranceRate.objects.all()


def listed_insurance_rates():
    return insurance_rates().order_by("-effective_from")


def find_insurance_rate(pk):
    return insurance_rates().filter(pk=pk).first()


def holidays():
    return PublicHoliday.objects.select_related("branch")


def listed_holidays():
    return holidays().order_by("-date")
