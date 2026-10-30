"""The reports pages: the index of what the member may read, and one report on screen or
exported (?format=pdf|xlsx, with the export permission)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.http import content_disposition_header

from apps.employees.services import visible_employees
from apps.iam.authz import permission_required
from apps.org.models import Branch, TenantProfile
from apps.org.services import visible_departments

from .exporters import EXPORTERS, shape
from .registry import REPORTS, SECTIONS, Report, Scope

EXPORT = "reports.export"


def visible_reports(actor) -> list[type[Report]]:
    return [report for report in REPORTS.values() if actor.can(report.permission)]


@permission_required("authenticated")
def home(request):
    """The dashboard (apps/reports/dashboard.py): each block for those allowed to see it."""
    from django.utils import timezone
    from django.utils.formats import date_format

    from apps.iam.models import Membership, MembershipStatus

    from .dashboard import figures

    actor = request.actor
    now = timezone.localtime()
    context = {"today_label": f"{date_format(now, 'l')} · {date_format(now, 'DATE_FORMAT')}",
               **figures(actor)}
    if actor.can("org.branch.view"):
        context["branch_count"] = Branch.objects.filter(is_active=True).count()
    if actor.can("admin.users.view"):
        context["member_count"] = Membership.objects.filter(
            status=MembershipStatus.ACTIVE).count()
    return render(request, "reports/dashboard.html", context)


@permission_required("authenticated")
def index(request):
    reports = visible_reports(request.actor)
    if not reports:
        raise PermissionDenied
    groups = [{"label": label, "icon": icon,
               "reports": [r for r in reports if r.section == key]}
              for key, label, icon in SECTIONS]
    return render(request, "reports/index.html",
                  {"groups": [group for group in groups if group["reports"]]})


def prepare(report: Report, query, actor):
    """The parsed filters and the reader's scope for `report`: the branches of its
    permission, and the branches, departments and employees the filters may choose from."""
    allowed = actor.branch_ids(report.permission) if actor is not None else None
    branches = Branch.objects.order_by("code")
    if allowed is not None:
        branches = branches.filter(pk__in=allowed)
    employees = visible_employees(actor, report.permission).order_by("code")
    options = {"branches": branches, "departments": visible_departments(actor, report.permission),
               "employees": employees}
    params = report.parse(query, **options)
    return params, Scope(allowed, params, actor), options


def export(report: Report, tables, params, fmt: str) -> HttpResponse:
    exporter = EXPORTERS[fmt]()
    response = HttpResponse(exporter.export(report, tables, params),
                            content_type=exporter.content_type)
    response["Content-Disposition"] = content_disposition_header(
        True, exporter.filename(report, params))
    response["X-Content-Type-Options"] = "nosniff"
    return response


def run_report(request, code):
    report_class = REPORTS.get(code)
    if report_class is None:
        raise Http404

    @permission_required(report_class.permission)
    def view(request):
        from apps.printing.pdf import PdfUnavailable

        report = report_class()
        params, scope, options = prepare(report, request.GET, request.actor)
        tables = report.run(params, scope)
        fmt = request.GET.get("format", "")
        if fmt in EXPORTERS:
            if not request.actor.can(EXPORT):
                raise PermissionDenied
            try:
                return export(report, tables, params, fmt)
            except PdfUnavailable:
                return render(request, "printing/pdf_unavailable.html", status=503)
        query = request.GET.copy()
        query.pop("format", None)
        return render(request, "reports/report.html", {
            "report": report, "tables": [shape(table) for table in tables],
            "params": params.values, "profile": TenantProfile.objects.first(),
            "query": query.urlencode(), "can_export": request.actor.can(EXPORT), **options,
        })

    return view(request)
