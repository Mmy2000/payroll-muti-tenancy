"""Loans, advances, incentives, penalties and pay items given: PayRole GHC14 (advances), GHC15
(loans and what is left), GHC16/GHC17 (installments paid or still due), GHP17/GHI13 (penalties
and incentives), GHB15/GHB16 (pay items given).

PayRole's date filters on GHC16/GHC17 never applied and GHC17's "principal" printed the paid
total; here every filter applies and each column is what its title says.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.adjustments.models import Adjustment, AdjustmentKind, BatchStatus
from apps.compensation.models import AssignmentStatus, PayItemAssignment
from apps.loans.models import (
    Advance,
    AdvanceStatus,
    InstallmentStatus,
    Loan,
    LoanInstallment,
    LoanStatus,
)

from ..registry import DATE_FILTERS, WHO_FILTERS, Column, Filter, Report, Table, register

ZERO = Decimal(0)


def _who(row) -> dict:
    person = row.employee
    return {"code": person.code, "name": person.name, "branch": person.branch.name}


WHO = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
       Column("branch", _("Branch"))]


def _in_range(params) -> tuple:
    return params.date("date_from"), params.date("date_to")


@register
class Advances(Report):
    code, section, permission = "advances", "pay", "loans.advance.view"
    title = _("Salary advances")
    description = _("Advances given in the period, and whether payroll has recovered them.")
    filters = (*DATE_FILTERS, *WHO_FILTERS, Filter("show", "choice", _("Show"), (
        ("all", _("All but cancelled")), ("open", _("To be recovered")),
        ("recovered", _("Recovered"))), "all"))

    def run(self, params, scope):
        rows = Advance.objects.filter(employee__in=scope.employees(),
                                      date__range=_in_range(params)
                                      ).select_related("employee__branch").order_by("date", "id")
        show = params.get("show")
        rows = rows.exclude(status=AdvanceStatus.CANCELLED) if show == "all" else \
            rows.filter(status=show)
        data = [{**_who(a), "date": a.date, "amount": a.amount, "status": a.get_status_display(),
                 "reason": a.reason} for a in rows]
        columns = [Column("date", _("Date"), "date"), *WHO, Column("amount", _("Amount"), "money"),
                   Column("status", _("Status")), Column("reason", _("Reason"))]
        return [Table(self.title, columns, data).add_totals("name", _("Total"), skip=("code",))]


@register
class LoanBalances(Report):
    code, section, permission = "loan_balances", "pay", "loans.loan.view"
    title = _("Loans and what is left")
    description = _("Loans granted in the period: the amount, what payroll has taken in "
                    "installments, and what is left.")
    filters = (*DATE_FILTERS, *WHO_FILTERS, Filter("show", "choice", _("Show"), (
        ("all", _("All but cancelled")), ("active", _("Being repaid")),
        ("settled", _("Repaid"))), "all"))

    def run(self, params, scope):
        loans = (Loan.objects.filter(employee__in=scope.employees(),
                                     granted_on__range=_in_range(params))
                 .select_related("employee__branch")
                 .annotate(paid=Sum("installments__amount",
                                    filter=Q(installments__status=InstallmentStatus.PAID)),
                           due=Sum("installments__amount",
                                   filter=Q(installments__status=InstallmentStatus.DUE)))
                 .order_by("granted_on", "id"))
        show = params.get("show")
        loans = loans.exclude(status=LoanStatus.CANCELLED) if show == "all" else \
            loans.filter(status=show)
        data = [{**_who(loan), "granted": loan.granted_on, "amount": loan.amount,
                 "paid": loan.paid or ZERO, "left": loan.due or ZERO,
                 "status": loan.get_status_display(),
                 "_urls": {"granted": reverse("loan", args=[loan.pk])}} for loan in loans]
        columns = [Column("granted", _("Granted on"), "date"), *WHO,
                   Column("amount", _("Amount"), "money"), Column("paid", _("Paid"), "money"),
                   Column("left", _("Left"), "money"), Column("status", _("Status"))]
        return [Table(self.title, columns, data).add_totals("name", _("Total"), skip=("code",))]


@register
class Installments(Report):
    code, section, permission = "installments", "pay", "loans.loan.view"
    title = _("Loan installments")
    description = _("Installments falling due in the period: paid by payroll, or still due.")
    filters = (*DATE_FILTERS, *WHO_FILTERS, Filter("show", "choice", _("Show"), (
        ("all", _("Paid and due")), ("due", _("Still due")), ("paid", _("Paid"))), "all"))

    def run(self, params, scope):
        start, end = _in_range(params)
        rows = (LoanInstallment.objects.filter(
            loan__employee__in=scope.employees(), due_month__range=(start.replace(day=1), end))
            .select_related("loan__employee__branch").order_by("due_month", "loan_id", "number"))
        show = params.get("show")
        rows = rows.exclude(status=InstallmentStatus.CANCELLED) if show == "all" else \
            rows.filter(status=show)
        data = [{**_who(i.loan), "month": i.due_month.strftime("%Y-%m"), "number": i.number,
                 "loan": i.loan.amount, "amount": i.amount, "status": i.get_status_display()}
                for i in rows]
        columns = [Column("month", _("Due month"), "code"), *WHO,
                   Column("number", _("Installment"), "int"),
                   Column("loan", _("Loan amount"), "money"),
                   Column("amount", _("Installment amount"), "money"),
                   Column("status", _("Status"))]
        return [Table(self.title, columns, data)
                .add_totals("name", _("Total"), skip=("code", "number", "loan"))]


class _Adjustments(Report):
    kind = ""
    section = "pay"
    filters = (*DATE_FILTERS, *WHO_FILTERS)

    def run(self, params, scope):
        rows = (Adjustment.objects.filter(kind=self.kind, batch__status=BatchStatus.APPROVED,
                                          employee__in=scope.employees(),
                                          date__range=_in_range(params))
                .select_related("employee__branch", "adjustment_type", "corrects")
                .order_by("date", "employee__code"))
        data = [{"date": a.date, **_who(a), "type": a.adjustment_type.name,
                 "counted": a.get_method_display(), "quantity": a.quantity, "amount": a.amount,
                 "reason": a.reason,
                 "note": _("Correction of %(day)s") % {"day": a.corrects.date.isoformat()}
                 if a.corrects_id else ""} for a in rows]
        columns = [Column("date", _("Date"), "date"), *WHO, Column("type", _("Type")),
                   Column("counted", _("Counted as")), Column("quantity", _("Quantity"), "qty"),
                   Column("amount", _("Amount"), "money"), Column("reason", _("Reason")),
                   Column("note", _("Note"))]
        return [Table(self.title, columns, data)
                .add_totals("name", _("Total"), skip=("code", "quantity"))]


@register
class Incentives(_Adjustments):
    code, kind, permission = "incentives", AdjustmentKind.INCENTIVE, "adjustments.incentive.view"
    title = _("Incentives given")
    description = _("Approved incentives dated in the period, corrections included.")


@register
class Penalties(_Adjustments):
    code, kind, permission = "penalties", AdjustmentKind.PENALTY, "adjustments.penalty.view"
    title = _("Penalties given")
    description = _("Approved penalties dated in the period, corrections included.")


@register
class PayItemsGiven(Report):
    code, section, permission = "pay_items_given", "pay", "compensation.entry.view"
    title = _("Pay items given")
    description = _("Pay items running at some time in the period: to whom, from when to "
                    "when, how often and how much.")
    filters = (*DATE_FILTERS, *WHO_FILTERS)

    def run(self, params, scope):
        start, end = _in_range(params)
        rows = (PayItemAssignment.objects.filter(
            employee__in=scope.employees(), starts_on__lte=end)
            .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=start))
            .exclude(status=AssignmentStatus.CANCELLED)
            .select_related("employee__branch", "item").order_by("employee__code", "starts_on"))
        data = [{**_who(a), "item": a.item.name, "kind": a.item.get_kind_display(),
                 "from": a.starts_on, "to": a.ends_on, "frequency": a.get_frequency_display(),
                 "amount": a.amount} for a in rows]
        columns = [*WHO, Column("item", _("Pay item")), Column("kind", _("Kind")),
                   Column("from", _("From"), "date"), Column("to", _("To"), "date"),
                   Column("frequency", _("How often")), Column("amount", _("Amount"), "money")]
        return [Table(self.title, columns, data)]
