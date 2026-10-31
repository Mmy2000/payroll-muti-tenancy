from django.db.models import Max, Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.compensation.models import (
    AssignmentStatus,
    ItemFrequency,
    PayItem,
    PayItemAssignment,
    PayItemBasis,
    PayItemKind,
)
from apps.core import months
from apps.core.listing import Choice, ListQuery
from apps.employees.selectors import visible_employees
from apps.employees.web.targets import target_choices
from apps.iam.authz import permission_required

from .. import permissions

ENTRY_VIEW = "compensation.entry.view"
STATUS_TABS = [(AssignmentStatus.ACTIVE, _lazy("In effect")),
               (AssignmentStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]


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


# --- items given to employees --------------------------------------------------------------


def _by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


@permission_required(ENTRY_VIEW)
def assignments(request):
    """The items running in a month (any day of it), for the employees the member may see."""
    month = months.parse(request.GET.get("month", ""), timezone.localdate())
    last = months.last_day(month)
    items = list(PayItem.objects.values_list("pk", "name"))
    found = ListQuery(request, permission=ENTRY_VIEW, search=("employee__name", "note"),
                      date_field="", branch_field="employee__branch_id",
                      party="employee_id", party_model="employees.Employee", keep=("month",),
                      choices=[Choice("item", _("Pay item"), [("", _("All items"))] + items,
                                      "item_id"),
                               Choice("status", _("Status"), STATUS_TABS, apply=_by_status,
                                      value=AssignmentStatus.ACTIVE, tabs=True)])
    rows = found.apply(PayItemAssignment.objects.filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=month), starts_on__lte=last,
        employee__in=visible_employees(request.actor, ENTRY_VIEW))
        .select_related("employee", "item"))
    return render(request, "compensation/assignments.html", {
        "filters": found, "page": found.page(rows.order_by("employee__code", "item__code")),
        "month": month, "previous": months.add_months(month, -1),
        "next": months.add_months(month, 1), "can_manage": request.actor.can(permissions.GIVE),
        "today": timezone.localdate()})


@permission_required(permissions.GIVE)
def assignment_new(request):
    return render(request, "compensation/assignment_form.html", {
        "items": PayItem.objects.filter(is_active=True), "today": timezone.localdate(),
        "frequencies": ItemFrequency.choices, "selected": request.GET.get("employee", ""),
        **target_choices(request.actor, permissions.GIVE)})
