"""Incentive and penalty pages: one set of views and templates, told apart by `KindPage`."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Sum
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.listing import Choice, ListQuery
from apps.employees.web.targets import target_choices
from apps.iam.authz import permission_required
from apps.org.models import Branch
from apps.org.selectors import visible_departments

from .. import selectors
from ..domain.amounts import METHODS
from ..models import AdjustmentBatch, AdjustmentKind, AdjustmentType, BatchStatus
from ..permissions import permission
from ..selectors import visible_batches


@dataclass(frozen=True)
class KindPage:
    """A kind's words and names. Pages are named `plural`, `<kind>-new`, `<kind>-batch` and
    `<kind>-types`; its API routes `<kind>-batch-…`, `<kind>-…` (rows) and `<kind>-type-…`."""

    kind: str
    plural: str
    title: object
    intro: object
    new_label: object
    types_title: object
    icon: str

    @property
    def view(self) -> str:
        return permission(self.kind, "view")

    @property
    def manage(self) -> str:
        return permission(self.kind, "manage")

    @property
    def approve(self) -> str:
        return permission(self.kind, "approve")


INCENTIVES = KindPage(
    AdjustmentKind.INCENTIVE, "incentives", _lazy("Incentives"),
    _lazy("Added to the pay of the period they're given in, once approved."),
    _lazy("Give an incentive"), _lazy("Incentive types"), "award")
PENALTIES = KindPage(
    AdjustmentKind.PENALTY, "penalties", _lazy("Penalties"),
    _lazy("Deducted from the pay of the period they're given in, once approved."),
    _lazy("Give a penalty"), _lazy("Penalty types"), "gavel")
STATUS_TABS = [(BatchStatus.DRAFT, _lazy("Drafts")), (BatchStatus.APPROVED, _lazy("Approved")),
               (BatchStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]


def _by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


def _for_employee(queryset, employee_id):
    return queryset.filter(rows__employee_id=employee_id)


def _target_names(batches) -> None:
    """`target_name` on each batch: who it was given to, in words."""
    names = {"department": {d.pk: d.label for d in visible_departments()},
             "branch": dict(Branch.objects.values_list("pk", "name"))}
    for batch in batches:
        if batch.corrects_id:
            batch.target_name = _("Correction")
        elif batch.target_kind in names:
            batch.target_name = names[batch.target_kind].get(batch.target_id, "—")
        else:
            batch.target_name = ""


def _list(request, page: KindPage):
    types = list(AdjustmentType.objects.filter(kind=page.kind).values_list("pk", "name"))
    found = ListQuery(request, permission=page.view, search=("reason", "rows__employee__name"),
                      date_field="date", branch_field="", party=_for_employee,
                      party_param="employee", party_model="employees.Employee",
                      choices=[Choice("type", _("Type"), [("", _("All types"))] + types,
                                      "adjustment_type_id"),
                               Choice("status", _("Status"), STATUS_TABS, apply=_by_status,
                                      value="all", tabs=True)])
    # Filter first, count after: a search through the rows must not count a row twice.
    matching = found.apply(visible_batches(request.actor, page.kind)).values("pk")
    result = found.page(AdjustmentBatch.objects.filter(pk__in=matching)
                        .select_related("adjustment_type")
                        .annotate(people=Count("rows"), total=Sum("rows__amount"))
                        .order_by("-date", "-id"))
    _target_names(result.object_list)
    return render(request, "adjustments/list.html", {
        "page_kind": page, "filters": found, "page": result,
        "can_manage": request.actor.can(page.manage)})


def _form(request, page: KindPage):
    return render(request, "adjustments/form.html", {
        "page_kind": page, "today": timezone.localdate(), "methods": METHODS.values(),
        "types": AdjustmentType.objects.filter(kind=page.kind, is_active=True),
        "selected": request.GET.get("employee", ""),
        "can_approve": request.actor.can(page.approve),
        **target_choices(request.actor, page.manage)})


def _batch(request, page: KindPage, pk: int):
    actor = request.actor
    batch = (visible_batches(actor, page.kind).select_related(
        "adjustment_type", "approved_by", "created_by", "updated_by", "corrects")
        .filter(pk=pk).first())
    if batch is None:
        raise Http404
    _target_names([batch])
    paid, now = selectors.paid_rows(batch), selectors.effective_amounts(batch)
    rows = list(batch.rows.select_related("employee", "corrects").order_by("employee__code"))
    latest = dict(batch.rows.model.objects.filter(
        corrects__batch=batch, batch__status=BatchStatus.APPROVED).order_by("id")
        .values_list("corrects_id", "quantity"))  # the last approved correction wins
    for row in rows:
        row.paid, row.effective = row.pk in paid, now[row.pk]
        row.current_quantity = latest.get(row.pk, row.quantity)
    draft, approved = batch.status == BatchStatus.DRAFT, batch.status == BatchStatus.APPROVED
    editable = draft and batch.corrects_id is None
    may_approve = actor.can(page.approve)
    return render(request, "adjustments/batch.html", {
        "page_kind": page, "batch": batch, "rows": rows, "paid": bool(paid),
        "total": sum((row.amount for row in rows), 0),
        "corrections": batch.corrections.select_related("adjustment_type").order_by("-id"),
        "can_edit": editable and actor.can(page.manage),
        "can_delete": draft and actor.can(page.manage),
        "can_approve": draft and may_approve,
        "can_reopen": approved and may_approve and not paid and not batch.corrections.exclude(
            status=BatchStatus.CANCELLED).exists(),
        "can_correct": approved and may_approve and batch.corrects_id is None
        and not batch.corrections.filter(status=BatchStatus.DRAFT).exists(),
        "today": timezone.localdate(), "methods": METHODS.values(),
        "types": AdjustmentType.objects.filter(kind=page.kind, is_active=True),
        **(target_choices(actor, page.manage) if editable else {}),
    })


def _types(request, page: KindPage):
    return render(request, "adjustments/types.html", {
        "page_kind": page, "types": AdjustmentType.objects.filter(kind=page.kind),
        "can_manage": request.actor.can(page.manage)})


@permission_required(INCENTIVES.view)
def incentives(request):
    return _list(request, INCENTIVES)


@permission_required(INCENTIVES.manage)
def incentive_new(request):
    return _form(request, INCENTIVES)


@permission_required(INCENTIVES.view)
def incentive_batch(request, pk):
    return _batch(request, INCENTIVES, pk)


@permission_required(INCENTIVES.view)
def incentive_types(request):
    return _types(request, INCENTIVES)


@permission_required(PENALTIES.view)
def penalties(request):
    return _list(request, PENALTIES)


@permission_required(PENALTIES.manage)
def penalty_new(request):
    return _form(request, PENALTIES)


@permission_required(PENALTIES.view)
def penalty_batch(request, pk):
    return _batch(request, PENALTIES, pk)


@permission_required(PENALTIES.view)
def penalty_types(request):
    return _types(request, PENALTIES)
