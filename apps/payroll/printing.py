"""Payslips on paper (PayRole Salary/payslip.py, GHS11a's bulk print): one payslip, or every
payslip of a run, one per page, as a PDF.

A payslip is printed from its frozen lines, so a reprint of an approved run is always what was
approved; a draft says so across the page. The employer's share of insurance is a cost to the
company, not on the employee's payslip.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from .models import PayrollRun
from .selectors import line_label


def document(slip) -> dict:
    """What a printed payslip shows."""
    lines = list(slip.lines.all())
    for line in lines:
        line.title = line_label(line)
    return {"slip": slip, "employee": slip.employee,
            "earnings": [line for line in lines if line.kind == "earning"],
            "deductions": [line for line in lines if line.kind == "deduction"]}


def payslips_pdf(run: PayrollRun, slips) -> bytes:
    """The payslips as one PDF (raises apps.printing.pdf.PdfUnavailable)."""
    from apps.printing.pdf import sheet_pdf

    return sheet_pdf("payroll/print/payslips.html", {
        "run": run, "documents": [document(slip) for slip in slips],
    }, title=_("Payslip"))


def filename(run: PayrollRun, slip=None) -> str:
    name = run.number or f"draft-{run.pk}"
    return f"payslip_{name}_{slip.employee.code}.pdf" if slip else f"payslips_{name}.pdf"
