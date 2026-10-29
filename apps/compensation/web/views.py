from django.db.models import Max
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from apps.compensation.models import PayItem, PayItemBasis, PayItemKind
from apps.iam.authz import permission_required


@permission_required("compensation.item.view")
def pay_items(request):
    return render(request, "compensation/pay_items.html",
                  {"items": PayItem.objects.order_by("code")})


def _form(request, item=None):
    return render(request, "compensation/pay_item_form.html", {
        "item": item,
        "next_code": (PayItem.objects.aggregate(top=Max("code"))["top"] or 0) + 1,
        "kinds": PayItemKind.choices,
        "bases": PayItemBasis.choices,
        "endpoint": (reverse("pay-item-detail", args=[item.pk]) if item
                     else reverse("pay-item-list")),
        "method": "PUT" if item else "POST",
    })


@permission_required("compensation.item.manage")
def pay_item_new(request):
    return _form(request)


@permission_required("compensation.item.manage")
def pay_item_edit(request, pk):
    item = PayItem.objects.filter(pk=pk).first()
    if item is None:
        raise Http404
    return _form(request, item)
