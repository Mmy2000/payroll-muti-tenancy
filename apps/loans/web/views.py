"""Advance and loan pages. They read and render; every save goes to the JSON API."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.listing import Choice, ListQuery
from apps.employees.web.targets import employee_choices
from apps.iam.authz import permission_required

from .. import permissions, selectors, validators
from ..models import AdvanceStatus, LoanStatus

ADVANCE_TABS = [(AdvanceStatus.OPEN, _lazy("To be recovered")),
                (AdvanceStatus.RECOVERED, _lazy("Recovered")),
                (AdvanceStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]
LOAN_TABS = [(LoanStatus.ACTIVE, _lazy("Being repaid")), (LoanStatus.SETTLED, _lazy("Repaid")),
             (LoanStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]


def _list_query(request, permission, date_field, tabs, default):
    return ListQuery(request, permission=permission, search=("employee__name", "reason"),
                     date_field=date_field, branch_field="employee__branch_id",
                     party="employee_id", party_model="employees.Employee",
                     choices=[Choice("status", _("Status"), tabs,
                                     apply=selectors.by_status, value=default, tabs=True)])


@permission_required(permissions.ADVANCE_VIEW)
def advance_list(request):
    found = _list_query(request, permissions.ADVANCE_VIEW, "date", ADVANCE_TABS,
                        AdvanceStatus.OPEN)
    rows = found.apply(selectors.visible_advances(request.actor))
    can_manage = request.actor.can(permissions.ADVANCE_MANAGE)
    return render(request, "loans/advances.html", {
        "filters": found, "page": found.page(rows),
        "can_manage": can_manage, "today": timezone.localdate(),
        "employees": (employee_choices(request.actor, permissions.ADVANCE_MANAGE)
                      if can_manage else []),
    })


@permission_required(permissions.VIEW)
def loan_list(request):
    found = _list_query(request, permissions.VIEW, "granted_on", LOAN_TABS, LoanStatus.ACTIVE)
    rows = found.apply(selectors.visible_loans(request.actor))
    return render(request, "loans/loans.html", {
        "filters": found, "page": found.page(rows),
        "can_manage": request.actor.can(permissions.MANAGE)})


@permission_required(permissions.MANAGE)
def loan_new(request):
    today = timezone.localdate()
    return render(request, "loans/loan_form.html", {
        "employees": employee_choices(request.actor, permissions.MANAGE), "today": today,
        "max_installments": validators.MAX_INSTALLMENTS,
        "selected": request.GET.get("employee", "")})


@permission_required(permissions.VIEW)
def loan_detail(request, pk):
    loan = selectors.visible_loan(request.actor, pk)
    if loan is None:
        raise Http404
    installments = list(selectors.installments_of(loan))
    return render(request, "loans/loan.html", {
        "loan": loan, "installments": installments,
        "repaid": sum(i.amount for i in installments if i.status == "paid"),
        "can_manage": request.actor.can(permissions.MANAGE, branch=loan.employee.branch_id)})
