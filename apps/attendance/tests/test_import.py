"""Importing clock times from Excel."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.attendance.imports import PunchImport
from apps.attendance.models import Punch
from apps.core.tenancy import tenant_context
from conftest import login

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sheet(rows):
    book = Workbook()
    sheet = book.active
    keys = [c.key for c in PunchImport.columns]
    sheet.append(keys)
    for row in rows:
        sheet.append([row.get(key) for key in keys])
    stream = io.BytesIO()
    book.save(stream)
    return SimpleUploadedFile("attendance.xlsx", stream.getvalue(), content_type=XLSX)


def test_importing_the_same_file_twice_adds_nothing_the_second_time(tenant_a, make_employee):
    make_employee(tenant_a, 7)
    rows = [{"employee_code": 7, "date": "2026-10-05", "check_in": "09:02",
             "check_out": "17:10"},
            {"employee_code": 7, "date": "2026-10-06", "check_in": "08:58"}]
    client = login(tenant_a)
    assert client.post("/attendance/import/", {"file": _sheet(rows)}).status_code == 302
    assert client.post("/attendance/import/", {"file": _sheet(rows)}).status_code == 302
    with tenant_context(tenant_a.id):
        assert Punch.objects.count() == 3


def test_a_bad_row_keeps_the_file_out(tenant_a, make_employee):
    make_employee(tenant_a, 7)
    rows = [{"employee_code": 7, "date": "2026-10-05", "check_in": "09:00"},
            {"employee_code": 99, "date": "2026-10-05", "check_in": "09:00"},
            {"employee_code": 7, "date": "2024-01-01", "check_in": "09:00"}]
    page = login(tenant_a, language="en").post("/attendance/import/",
                                               {"file": _sheet(rows)}).content.decode()
    assert "Nothing was imported" in page and "employee_code" in page
    with tenant_context(tenant_a.id):
        assert not Punch.objects.exists()


def test_the_template(tenant_a):
    response = login(tenant_a).get("/attendance/import/template.xlsx")
    assert response.status_code == 200 and response.content[:2] == b"PK"
