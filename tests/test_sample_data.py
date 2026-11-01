"""The sample company still builds, through the real services, with every case it promises."""

import pytest
from django.utils import timezone

from apps.attendance.models import HourlyLeave, LeaveRequest, Punch
from apps.core.tenancy import tenant_context
from apps.employees.models import Employee, EmployeeAssignment
from apps.org.models import Branch, Department
from apps.org.timezones import tenant_zone_name, zone
from apps.payroll.models import PayrollRun
from apps.platform.console import sample
from apps.platform.tenants.models import TenantFeature

pytestmark = pytest.mark.django_db


def test_the_sample_company_has_what_there_is_to_try(tenant_a):
    with tenant_context(tenant_a.id), timezone.override(zone(tenant_zone_name(tenant_a.id))):
        made = sample.seed(tenant_a, "Sample-Pass-2026", people=60, months=2)
        assert Branch.objects.filter(is_active=False).exists()
        assert Department.objects.filter(is_active=False).exists()
        assert Department.objects.get(name="المبيعات").placements.count() == 5
        assert made["employees"] == 63
        assert Employee.objects.filter(left_on__isnull=False).exists()  # people who left
        assert Employee.objects.filter(hired_on__gt=timezone.localdate()).exists()  # yet to start
        assert Employee.objects.filter(department__isnull=True).exists()
        assert EmployeeAssignment.objects.exclude(ended_on=None).exists()  # came back
        statuses = set(LeaveRequest.objects.values_list("status", flat=True))
        assert {"approved", "pending", "rejected", "cancelled"} <= statuses
        assert HourlyLeave.objects.exists() and Punch.objects.count() > 1000
        runs = set(PayrollRun.objects.values_list("status", flat=True))
        assert {"draft", "approved", "paid"} <= runs, runs
        assert TenantFeature.objects.filter(key="mobile_app", enabled=True).exists()
