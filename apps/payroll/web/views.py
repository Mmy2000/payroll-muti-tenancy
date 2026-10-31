"""Payroll pages. They read and render; every change goes to the JSON API."""

from __future__ import annotations

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.listing import Choice, ListQuery
from apps.iam.authz import permission_required
from apps.org.models import Branch
from apps.org.selectors import visible_departments

from .. import permissions, printing, services
from ..models import Frequency, MonthlyRule, PeriodKind, RunStatus, ScopeKind
from ..selectors import issue_text, line_label, visible_runs

RUN_TABS = [(RunStatus.DRAFT, _lazy("Drafts")), (RunStatus.APPROVED, _lazy("Approved")),
            (RunStatus.PAID, _lazy("Paid")), (RunStatus.REVERSED, _lazy("Reversed")),
            ("all", _lazy("All"))]


def _by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


def _scope_names(runs) -> dict:
    """{(scope, id): name} for the branches and departments the runs are for."""
    ids = {kind: {r.scope_id for r in runs if r.scope == kind}
           for kind in (ScopeKind.BRANCH, ScopeKind.DEPARTMENT)}
    names = {(ScopeKind.BRANCH, b.pk): b.name
             for b in Branch.objects.filter(pk__in=ids[ScopeKind.BRANCH])}
    names.update({(ScopeKind.DEPARTMENT, d.pk): d.label
                  for d in visible_departments().filter(pk__in=ids[ScopeKind.DEPARTMENT])})
    return names


def _with_scope_names(runs):
    names = _scope_names(runs)
    for run in runs:
        run.scope_name = (_("Everyone") if run.scope == ScopeKind.ALL
                          else names.get((run.scope, run.scope_id), "—"))
    return runs


def _run_or_404(request, pk):
    run = visible_runs(request.actor).filter(pk=pk).first()
    if run is None:
        raise Http404
    return run


@permission_required(permissions.READ)
def runs(request):
    found = ListQuery(request, permission=permissions.READ, search=("number", "note"),
                      date_field="period__end", branch_field="",
                      choices=[Choice("status", _("Status"), RUN_TABS, apply=_by_status,
                                      value=RunStatus.DRAFT, tabs=True),
                               Choice("frequency", _("Pay frequency"), Frequency.choices,
                                      "period__frequency")])
    page = found.page(found.apply(visible_runs(request.actor)).order_by("-period__start", "-id"))
    _with_scope_names(page.object_list)
    return render(request, "payroll/runs.html", {
        "filters": found, "page": page, "can_calculate": request.actor.can(permissions.CALCULATE)})


@permission_required(permissions.CALCULATE)
def run_new(request):
    allowed = request.actor.branch_ids(permissions.CALCULATE)
    branches = Branch.objects.filter(is_active=True).order_by("code")
    today = timezone.localdate()
    return render(request, "payroll/run_form.html", {
        "frequencies": Frequency.choices, "kinds": PeriodKind.choices, "today": today,
        "periods": [(label, services.period_on(f, today)) for f, label in Frequency.choices],
        # A member limited to some branches runs payroll branch by branch.
        "all_branches": allowed is None,
        "branches": branches if allowed is None else branches.filter(pk__in=allowed),
        "departments": visible_departments().filter(is_active=True),
    })


@permission_required(permissions.READ)
def run_detail(request, pk):
    run = _run_or_404(request, pk)
    _with_scope_names([run])
    slips = list(run.payslips.select_related("employee").order_by("employee__code"))
    actor = request.actor
    can = {code: actor.can(code, branch=run.scope_id if run.scope == ScopeKind.BRANCH
                           else None)
           for code in (permissions.CALCULATE, permissions.APPROVE, permissions.PAY,
                        permissions.REVERSE)}
    return render(request, "payroll/run.html", {
        "run": run, "slips": slips, "today": timezone.localdate(),
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
    slip = run.payslips.select_related("employee").filter(pk=slip_pk).first()
    if slip is None:
        raise Http404
    lines = list(slip.lines.all())
    for line in lines:
        line.title = line_label(line)
    can_calculate = run.is_draft and request.actor.can(
        permissions.CALCULATE, branch=run.scope_id if run.scope == ScopeKind.BRANCH else None)
    return render(request, "payroll/payslip.html", {
        "run": run, "slip": slip,
        "earnings": [line for line in lines if line.kind == "earning"],
        "deductions": [line for line in lines if line.kind == "deduction"],
        "employer": [line for line in lines if line.kind == "employer"],
        "issues": [{"severity": i["severity"], "text": issue_text(i)} for i in slip.issues],
        "manual_lines": run.manual_lines.filter(employee=slip.employee).order_by("pk"),
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
    slip = run.payslips.select_related("employee__branch", "employee__department").filter(
        pk=slip_pk).first()
    if slip is None:
        raise Http404
    return _pdf(request, run, [slip], printing.filename(run, slip))


@permission_required(permissions.READ)
def run_payslips_pdf(request, pk):
    run = _run_or_404(request, pk)
    slips = run.payslips.select_related("employee__branch", "employee__department")
    if not slips.exists():
        raise Http404
    return _pdf(request, run, slips, printing.filename(run))


@permission_required(permissions.SETUP)
def calendars(request):
    return render(request, "payroll/calendars.html", {
        "calendars": [services.calendar_for(f) for f in Frequency.values],
        "monthly_rules": MonthlyRule.choices, "today": timezone.localdate(),
    })
