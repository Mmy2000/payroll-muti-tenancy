"""The page of an Excel import (apps.core.imports): the upload form, the template download and,
after a failed attempt, every row's problems. Each import gives its words and addresses:

    @permission_required("attendance.import")
    def punch_import(request):
        return import_page(request, PunchImport(actor=request.actor), ImportPage(
            title=_("Import attendance"), intro=_("…"), back_url=reverse("attendance"),
            back_label=_("Attendance"), template_url=reverse("attendance-import-template"),
            done_url=reverse("attendance"), done_message=_("%(count)s rows imported.")))
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from .imports import ImportFailed, SheetImport

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class ImportPage:
    title: object
    intro: object
    back_url: str
    back_label: object
    template_url: str
    done_url: str
    done_message: object  # with %(count)s


def import_page(request, importer: SheetImport, page: ImportPage):
    report = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, _("Choose an Excel file."))
        else:
            try:
                report = importer.run(upload)
            except ImportFailed as failed:
                report = failed.report
            if not report.errors:
                messages.success(request, str(page.done_message) % {"count": report.created})
                return redirect(page.done_url)
    return render(request, "components/import_page.html",
                  {"page": page, "report": report, "columns": importer.columns})


def template_download(importer: SheetImport, filename: str) -> HttpResponse:
    response = HttpResponse(importer.template(), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
