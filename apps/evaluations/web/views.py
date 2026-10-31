"""Evaluation pages: the list, writing one, and its card as a PDF (PayRole GHV11, GHV11a)."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.listing import ListQuery
from apps.employees.web.targets import employee_choices
from apps.iam.authz import permission_required

from .. import permissions, selectors


@permission_required(permissions.VIEW)
def evaluations(request):
    found = ListQuery(request, permission=permissions.VIEW,
                      search=("employee__name", "note_1", "note_2", "note_3", "note_4"),
                      date_field="evaluated_on", branch_field="employee__branch_id",
                      party="employee_id", party_param="employee",
                      party_model="employees.Employee")
    rows = found.apply(selectors.visible(request.actor))
    return render(request, "evaluations/evaluations.html", {
        "filters": found, "page": found.page(rows.order_by("-year", "-number")),
        "can_manage": request.actor.can(permissions.MANAGE)})


def _form(request, row=None):
    today = timezone.localdate()
    return render(request, "evaluations/form.html", {
        "row": row, "employees": employee_choices(request.actor, permissions.MANAGE),
        "year": row.year if row else today.year - (1 if today.month <= 3 else 0),
        "today": today, "selected": str(row.employee_id) if row else
        request.GET.get("employee", ""),
        "next_number": row.number if row else selectors.next_number()})


@permission_required(permissions.MANAGE)
def evaluation_new(request):
    return _form(request)


@permission_required(permissions.VIEW)
def evaluation(request, pk):
    row = selectors.visible(request.actor).filter(pk=pk).first()
    if row is None:
        raise Http404
    if request.actor.can(permissions.MANAGE, branch=row.employee.branch_id):
        return _form(request, row)
    return render(request, "evaluations/detail.html", {
        "row": row, "facts": selectors.card(row, request.actor)})


@permission_required(permissions.VIEW)
def evaluation_pdf(request, pk):
    from apps.printing.pdf import PdfUnavailable, pdf_response, sheet_pdf

    row = selectors.visible(request.actor).filter(pk=pk).first()
    if row is None:
        raise Http404
    try:
        content = sheet_pdf("evaluations/card.html", {
            "row": row, "facts": selectors.card(row, request.actor)},
            title=_("Evaluation card"))
    except PdfUnavailable:
        return render(request, "printing/pdf_unavailable.html", status=503)
    return pdf_response(content, f"evaluation_{row.number}_{row.year}.pdf",
                        inline=request.GET.get("inline") == "1")
