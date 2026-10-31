from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.compensation.models import (
    AssignmentStatus,
    ItemFrequency,
    PayItemBasis,
    PayItemKind,
)
from apps.core import months
from apps.core.listing import Choice, ListQuery
from apps.employees.web.targets import target_choices
from apps.iam.authz import permission_required

from .. import permissions, selectors

STATUS_TABS = [(AssignmentStatus.ACTIVE, _lazy("In effect")),
               (AssignmentStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]


@permission_required("compensation.item.view")
def pay_items(request):
    return render(request, "compensation/pay_items.html",
                  {"items": selectors.pay_items()})


def _form(request, item=None):
    return render(request, "compensation/pay_item_form.html", {
        "item": item,
        "next_code": selectors.next_pay_item_code(),
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
    item = selectors.find_pay_item(pk)
    if item is None:
        raise Http404
    return _form(request, item)


# --- items given to employees --------------------------------------------------------------


@permission_required(permissions.ENTRY_VIEW)
def assignments(request):
    """The items running in a month (any day of it), for the employees the member may see."""
    month = months.parse(request.GET.get("month", ""), timezone.localdate())
    last = months.last_day(month)
    items = selectors.pay_item_choices()
    found = ListQuery(request, permission=permissions.ENTRY_VIEW,
                      search=("employee__name", "note"),
                      date_field="", branch_field="employee__branch_id",
                      party="employee_id", party_model="employees.Employee", keep=("month",),
                      choices=[Choice("item", _("Pay item"), [("", _("All items"))] + items,
                                      "item_id"),
                               Choice("status", _("Status"), STATUS_TABS,
                                      apply=selectors.by_status, value=AssignmentStatus.ACTIVE,
                                      tabs=True)])
    rows = found.apply(selectors.assignments_running(request.actor, month, last))
    return render(request, "compensation/assignments.html", {
        "filters": found, "page": found.page(rows),
        "month": month, "previous": months.add_months(month, -1),
        "next": months.add_months(month, 1), "can_manage": request.actor.can(permissions.GIVE),
        "today": timezone.localdate()})


@permission_required(permissions.GIVE)
def assignment_new(request):
    return render(request, "compensation/assignment_form.html", {
        "items": selectors.active_pay_items(), "today": timezone.localdate(),
        "frequencies": ItemFrequency.choices, "selected": request.GET.get("employee", ""),
        **target_choices(request.actor, permissions.GIVE)})
