"""Payroll reports, read from the frozen payslips (never worked out again): the register of
every payslip (PayRole GHS12, كشف المرتبات) and the totals of each run by branch (GHS14).

Reversed runs never count. By default only approved and paid runs do; drafts can be shown on
their own, to check them before approval.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.payroll.models import Payslip, PayslipLine, RunStatus

from ..registry import DATE_FILTERS, WHO_FILTERS, Column, Filter, Report, Table, register

READ = "payroll.run.read"
ZERO = Decimal(0)
RUNS = (("final", _("Approved and paid")), ("paid", _("Paid only")),
        ("draft", _("Drafts only")))
STATUSES = {"final": (RunStatus.APPROVED, RunStatus.PAID), "paid": (RunStatus.PAID,),
            "draft": (RunStatus.DRAFT,)}
RUN_FILTER = Filter("runs", "choice", _("Runs"), RUNS, "final")

# The register's money columns, in order: (key, label).
EARNINGS = [("pay", _("Salary or wages")), ("extra", _("Overtime and holiday work")),
            ("items_plus", _("Pay items added")), ("incentives", _("Incentives")),
            ("other_plus", _("Other additions"))]
DEDUCTIONS = [("absence", _("Absence")), ("time", _("Lateness and missing time")),
              ("penalties", _("Penalties")), ("advances", _("Advances")),
              ("installments", _("Loan installments")), ("items_minus", _("Pay items deducted")),
              ("insurance", _("Social insurance")), ("tax", _("Income tax")),
              ("other_minus", _("Other deductions"))]
_BY_CODE = {
    "earning": {"salary": "pay", "day_wage": "pay", "hour_wage": "pay", "overtime": "extra",
                "holiday_work": "extra", "item": "items_plus", "incentive": "incentives"},
    "deduction": {"days_not_paid": "absence", "absence_penalty": "absence", "lateness": "time",
                  "missing_time": "time", "penalty": "penalties", "advance": "advances",
                  "installment": "installments", "item": "items_minus",
                  "insurance_employee": "insurance", "income_tax": "tax"},
}


def register_column(code: str, kind: str) -> str | None:
    """The register column a payslip line adds to; None for the employer's cost (a column of
    its own). Pure."""
    if kind not in _BY_CODE:
        return None
    return _BY_CODE[kind].get(code, "other_plus" if kind == "earning" else "other_minus")


def period_text(period) -> str:
    """A period in a few characters: "2026-10" for a calendar month, else "26/09–25/10"."""
    start, end = period.start, period.end
    if start.day == 1 and (end.month != (end + timedelta(days=1)).month) \
            and (start.year, start.month) == (end.year, end.month):
        return f"{start:%Y-%m}"
    return f"{start:%d/%m}–{end:%d/%m/%Y}"


def _payslips(params, scope):
    slips = (Payslip.objects.filter(
        run__status__in=STATUSES[params.get("runs")],
        run__period__end__range=(params.date("date_from"), params.date("date_to")),
        employee__in=scope.employees())
        .select_related("employee__branch", "employee__department", "run__period"))
    return slips.order_by("run__period__start", "employee__code")


@register
class PayrollRegister(Report):
    code, section, permission = "payroll_register", "payroll", READ
    title = _("Payroll register")
    description = _("Every payslip of the runs ending in the period: what was earned and "
                    "deducted, by kind, and the net.")
    filters = (*DATE_FILTERS, *WHO_FILTERS, RUN_FILTER)

    def run(self, params, scope):
        slips = list(_payslips(params, scope))
        amounts = defaultdict(lambda: defaultdict(lambda: ZERO))
        used = set()  # kinds some payslip has: the others' columns are left out
        for line in PayslipLine.objects.filter(payslip__in=slips).only(
                "payslip_id", "code", "kind", "amount"):
            key = register_column(line.code, line.kind) or "employer"
            amounts[line.payslip_id][key] += line.amount
            used.add(key)
        columns = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("branch", _("Branch")), Column("department", _("Department")),
                   Column("period", _("Period"), "code"), Column("run", _("Run"), "code"),
                   *[Column(key, label, "money") for key, label in EARNINGS if key in used],
                   Column("earnings", _("Earnings"), "money"),
                   *[Column(key, label, "money") for key, label in DEDUCTIONS if key in used],
                   Column("deductions", _("Deductions"), "money"),
                   Column("net", _("Net"), "money"),
                   Column("employer", _("Employer's cost"), "money")]
        rows = []
        for slip in slips:
            run, person = slip.run, slip.employee
            values = amounts[slip.pk]
            rows.append({
                "code": person.code, "name": person.name, "branch": person.branch.name,
                "department": person.department.name if person.department else "",
                "period": period_text(run.period), "run": run.number or _("Draft"),
                **{key: values[key] for key, _label in EARNINGS + DEDUCTIONS},
                "earnings": slip.earnings, "deductions": slip.deductions, "net": slip.net,
                "employer": slip.employer_cost,
                "_urls": {"name": reverse("payslip", args=[run.pk, slip.pk])}})
        table = Table(self.title, columns, rows)
        return [table.add_totals("name", _("Total"), skip=("code",))]


@register
class PayrollSummary(Report):
    code, section, permission = "payroll_summary", "payroll", READ
    title = _("Payroll totals by run and branch")
    description = _("For each run ending in the period and each branch: how many were paid, "
                    "earnings, deductions, net and the employer's cost.")
    filters = (*DATE_FILTERS, *WHO_FILTERS, RUN_FILTER)

    def run(self, params, scope):
        groups: dict = {}
        for slip in _payslips(params, scope):
            key = (slip.run_id, slip.employee.branch_id)
            group = groups.setdefault(key, {
                "period": period_text(slip.run.period),
                "run": slip.run.number or _("Draft"), "status": slip.run.get_status_display(),
                "branch": slip.employee.branch.name, "people": 0, "earnings": ZERO,
                "deductions": ZERO, "net": ZERO, "employer": ZERO,
                "_urls": {"run": reverse("payroll-run", args=[slip.run_id])}})
            group["people"] += 1
            for key_, value in (("earnings", slip.earnings), ("deductions", slip.deductions),
                                ("net", slip.net), ("employer", slip.employer_cost)):
                group[key_] += value
        columns = [Column("period", _("Period"), "code"), Column("run", _("Run"), "code"),
                   Column("status", _("Status")), Column("branch", _("Branch")),
                   Column("people", _("Employees"), "int"),
                   Column("earnings", _("Earnings"), "money"),
                   Column("deductions", _("Deductions"), "money"),
                   Column("net", _("Net"), "money"),
                   Column("employer", _("Employer's cost"), "money")]
        table = Table(self.title, columns, list(groups.values()))
        return [table.add_totals("period", _("Total"))]
