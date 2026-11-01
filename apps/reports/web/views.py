"""The reports pages: the index of what the member may read, and one report on screen or
exported (?format=pdf|xlsx, with the export permission)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.http import content_disposition_header

from apps.iam.authz import permission_required
from apps.iam.selectors import active_member_count
from apps.org.listing import page_of
from apps.org.selectors import (
    active_branch_count,
    branches_by_code,
    tenant_profile_or_none,
    visible_departments,
)

from ..exporters import EXPORTERS, shape
from ..registry import REPORTS, SECTIONS, Report, Scope
from ..selectors import employees_by_code, figures

EXPORT = "reports.export"


def visible_reports(actor) -> list[type[Report]]:
    return [report for report in REPORTS.values() if actor.can(report.permission)]


@permission_required("authenticated")
def home(request):
    """The dashboard (apps/reports/selectors.py): each block for those allowed to see it."""
    from django.utils import timezone
    from django.utils.formats import date_format

    actor = request.actor
    now = timezone.localtime()
    context = {"today_label": f"{date_format(now, 'l')} · {date_format(now, 'DATE_FORMAT')}",
               **figures(actor)}
    if actor.can("org.branch.view"):
        context["branch_count"] = active_branch_count()
    if actor.can("admin.users.view"):
        context["member_count"] = active_member_count()
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
    options = {"branches": branches_by_code(allowed),
               "departments": visible_departments(actor, report.permission),
               "employees": employees_by_code(actor, report.permission)}
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
        query.pop("page", None)
        shaped = [shape(table) for table in tables]
        # The screen shows a page; totals, prints and exports are of everything. A report of
        # several tables is a summary, and each of them short.
        page = page_of(request, shaped[0]["rows"]) if len(shaped) == 1 else None
        if page is not None:
            shaped[0]["rows"] = page.object_list
        return render(request, "reports/report.html", {
            "report": report, "tables": shaped, "page": page,
            "params": params.chosen, "profile": tenant_profile_or_none(),
            "query": query.urlencode(), "can_export": request.actor.can(EXPORT), **options,
        })

    return view(request)
