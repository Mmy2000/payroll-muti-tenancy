"""Advance and loan pages. They read and render; every save goes to the JSON API."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.listing import Choice, ListQuery
from apps.employees.selectors import visible_employees
from apps.employees.web.targets import employee_choices
from apps.iam.authz import permission_required

from .. import permissions, validators
from ..models import Advance, AdvanceStatus, Loan, LoanStatus
from ..services import advances

ADVANCE_TABS = [(AdvanceStatus.OPEN, _lazy("To be recovered")),
                (AdvanceStatus.RECOVERED, _lazy("Recovered")),
                (AdvanceStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]
LOAN_TABS = [(LoanStatus.ACTIVE, _lazy("Being repaid")), (LoanStatus.SETTLED, _lazy("Repaid")),
             (LoanStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]


def _by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


def _list_query(request, permission, date_field, tabs, default):
    return ListQuery(request, permission=permission, search=("employee__name", "reason"),
                     date_field=date_field, branch_field="employee__branch_id",
                     party="employee_id", party_model="employees.Employee",
                     choices=[Choice("status", _("Status"), tabs, apply=_by_status,
                                     value=default, tabs=True)])


@permission_required(advances.VIEW)
def advance_list(request):
    found = _list_query(request, advances.VIEW, "date", ADVANCE_TABS, AdvanceStatus.OPEN)
    rows = found.apply(Advance.objects.filter(
        employee__in=visible_employees(request.actor, advances.VIEW)).select_related("employee"))
    can_manage = request.actor.can(advances.MANAGE)
    return render(request, "loans/advances.html", {
        "filters": found, "page": found.page(rows.order_by("-date", "-id")),
        "can_manage": can_manage, "today": timezone.localdate(),
        "employees": employee_choices(request.actor, advances.MANAGE) if can_manage else [],
    })


@permission_required(permissions.VIEW)
def loan_list(request):
    found = _list_query(request, permissions.VIEW, "granted_on", LOAN_TABS, LoanStatus.ACTIVE)
    rows = found.apply(Loan.objects.filter(
        employee__in=visible_employees(request.actor, permissions.VIEW))
        .select_related("employee").prefetch_related("installments"))
    return render(request, "loans/loans.html", {
        "filters": found, "page": found.page(rows.order_by("-granted_on", "-id")),
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
    loan = (Loan.objects.filter(employee__in=visible_employees(request.actor, permissions.VIEW))
            .select_related("employee").filter(pk=pk).first())
    if loan is None:
        raise Http404
    installments = list(loan.installments.all())
    return render(request, "loans/loan.html", {
        "loan": loan, "installments": installments,
        "repaid": sum(i.amount for i in installments if i.status == "paid"),
        "can_manage": request.actor.can(permissions.MANAGE, branch=loan.employee.branch_id)})
