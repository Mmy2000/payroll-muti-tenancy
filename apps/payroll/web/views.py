"""Payroll pages. They read and render; every change goes to the JSON API."""

from __future__ import annotations

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.iam.authz import permission_required
from apps.org.listing import Choice, ListQuery, page_of
from apps.org.selectors import active_departments, branch_choices

from .. import permissions, printing, selectors
from ..models import Frequency, MonthlyRule, PeriodKind, RunStatus, ScopeKind
from ..services import calendars as calendar_services

RUN_TABS = [(RunStatus.DRAFT, _lazy("Drafts")), (RunStatus.APPROVED, _lazy("Approved")),
            (RunStatus.PAID, _lazy("Paid")), (RunStatus.REVERSED, _lazy("Reversed")),
            ("all", _lazy("All"))]


def _with_scope_names(runs):
    names = selectors.scope_names(runs)
    for run in runs:
        run.scope_name = (_("Everyone") if run.scope == ScopeKind.ALL
                          else names.get((run.scope, run.scope_id), "—"))
        if run.scope_branch_id:
            branch = names.get((ScopeKind.BRANCH, run.scope_branch_id), "—")
            run.scope_name = f"{run.scope_name} · {branch}"
    return runs


def _run_or_404(request, pk):
    run = selectors.find_run(request.actor, pk)
    if run is None:
        raise Http404
    return run


@permission_required(permissions.READ)
def runs(request):
    found = ListQuery(request, permission=permissions.READ, search=("number", "note"),
                      date_field="period__end", branch_field="",
                      choices=[Choice("status", _("Status"), RUN_TABS, apply=selectors.with_status,
                                      value=RunStatus.DRAFT, tabs=True),
                               Choice("frequency", _("Pay frequency"), Frequency.choices,
                                      "period__frequency")])
    page = found.page(found.apply(selectors.runs_newest_first(request.actor)))
    _with_scope_names(page.object_list)
    return render(request, "payroll/runs.html", {
        "filters": found, "page": page, "can_calculate": request.actor.can(permissions.CALCULATE)})


@permission_required(permissions.CALCULATE)
def run_new(request):
    allowed = request.actor.branch_ids(permissions.CALCULATE)
    today = timezone.localdate()
    return render(request, "payroll/run_form.html", {
        "frequencies": Frequency.choices, "kinds": PeriodKind.choices, "today": today,
        "periods": [(label, calendar_services.period_on(f, today))
                    for f, label in Frequency.choices],
        # A member limited to some branches runs payroll branch by branch.
        "all_branches": allowed is None,
        "branches": branch_choices(allowed),
        "departments": active_departments(),
    })


@permission_required(permissions.READ)
def run_detail(request, pk):
    run = _run_or_404(request, pk)
    _with_scope_names([run])
    slips = list(selectors.slips_by_code(run))
    actor = request.actor
    can = {code: actor.can(code, branch=run.branch_in_scope)
           for code in (permissions.CALCULATE, permissions.APPROVE, permissions.PAY,
                        permissions.REVERSE)}
    return render(request, "payroll/run.html", {
        "run": run, "slips": slips, "page": page_of(request, slips),
        "today": timezone.localdate(),
        "blocked": sum(1 for s in slips if s.blocking),
        "warned": sum(1 for s in slips if s.warnings and not s.blocking),
        "can_calculate": run.is_draft and can[permissions.CALCULATE],
        "can_approve": run.is_draft and can[permissions.APPROVE],
        "can_pay": run.status == RunStatus.APPROVED and can[permissions.PAY],
        "can_reverse": run.status == RunStatus.APPROVED and can[permissions.REVERSE],
        "can_whatsapp": run.status in (RunStatus.APPROVED, RunStatus.PAID)
        and request.actor.can("messaging.send"),
    })


@permission_required(permissions.READ)
def payslip_detail(request, pk, slip_pk):
    run = _run_or_404(request, pk)
    slip = selectors.find_slip(run, slip_pk)
    if slip is None:
        raise Http404
    lines = selectors.labelled_lines(slip)
    can_calculate = run.is_draft and request.actor.can(
        permissions.CALCULATE, branch=run.branch_in_scope)
    return render(request, "payroll/payslip.html", {
        "run": run, "slip": slip,
        "earnings": [line for line in lines if line.kind == "earning"],
        "deductions": [line for line in lines if line.kind == "deduction"],
        "employer": [line for line in lines if line.kind == "employer"],
        "issues": [{"severity": i["severity"], "text": selectors.issue_text(i)}
                   for i in slip.issues],
        "manual_lines": selectors.manual_lines_for(run, slip.employee),
        "can_calculate": can_calculate,
        "snapshot": json.dumps(slip.snapshot, indent=2, ensure_ascii=False,
                               cls=DjangoJSONEncoder),
    })


def _pdf(request, run, slips, name):
    from apps.printing.pdf import PdfUnavailable, pdf_response

    try:
        return pdf_response(printing.payslips_pdf(run, slips), name,
                            inline=request.GET.get("inline") == "1")
    except PdfUnavailable:
        return render(request, "printing/pdf_unavailable.html", status=503)


@permission_required(permissions.READ)
def payslip_pdf(request, pk, slip_pk):
    run = _run_or_404(request, pk)
    slip = selectors.find_slip_to_print(run, slip_pk)
    if slip is None:
        raise Http404
    return _pdf(request, run, [slip], printing.filename(run, slip))


@permission_required(permissions.READ)
def run_payslips_pdf(request, pk):
    run = _run_or_404(request, pk)
    if not selectors.has_slips(run):
        raise Http404
    return _pdf(request, run, selectors.slips_to_print(run), printing.filename(run))


@permission_required(permissions.SETUP)
def calendars(request):
    return render(request, "payroll/calendars.html", {
        "calendars": [calendar_services.calendar_for(f) for f in Frequency.values],
        "monthly_rules": MonthlyRule.choices, "today": timezone.localdate(),
    })
