"""Payroll runs end to end, against the database: the workflow and the acceptance criteria of
"PayRole — Phase 4 Payroll Decisions"."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.adjustments.models import AdjustmentType
from apps.adjustments.services.batches import AdjustmentInput
from apps.adjustments.services.batches import give as give_adjustment
from apps.compensation.models import PayItem
from apps.compensation.services import AssignmentInput, give_items
from apps.core.errors import Conflict, DomainError
from apps.core.tenancy import tenant_context
from apps.employees.selectors import Target
from apps.employees.services.employees import CompensationInput, change_pay
from apps.loans.models import InstallmentStatus, LoanStatus
from apps.loans.services.loans import LoanInput, grant_loan
from apps.payroll.models import PaidSource, RunStatus
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from apps.policies.models import InsuranceRate

from ..services import calendars, lifecycle, manual_lines, runs

pytestmark = pytest.mark.django_db

OCTOBER = date(2026, 10, 15)


def _without_attendance(tenant):
    """Fixed salaries need no attendance; switching it off keeps these runs about pay rules."""
    TenantFeature.objects.create(tenant=tenant, key="attendance", enabled=False)
    features.forget(tenant.pk)


def _run(day=OCTOBER, frequency="monthly", **extra):
    return runs.create_run(runs.RunInput(frequency=frequency, day=day, **extra))


def _lines(slip):
    return {line.code: line.amount for line in slip.lines.all()}


@pytest.fixture
def client_a(tenant_a):
    _without_attendance(tenant_a)
    return tenant_a


def test_a_monthly_run_with_a_custom_start_day(client_a, make_employee):
    make_employee(client_a)
    with tenant_context(client_a.id):
        calendars.save_calendar(calendars.CalendarInput("monthly", start_day=26))
        run = _run()
        assert (run.period.start, run.period.end) == (date(2026, 9, 26), date(2026, 10, 25))
        slip = run.payslips.get()
        assert slip.net == D(6000) and _lines(slip) == {"salary": D(6000)}
        # The calendar can't move once runs exist.
        with pytest.raises(DomainError):
            calendars.save_calendar(calendars.CalendarInput("monthly", start_day=1))


def test_approve_and_pay_freeze_the_run(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        run = _run()
        lifecycle.approve_run(run.pk)
        run.refresh_from_db()
        assert run.status == RunStatus.APPROVED and run.number.startswith("PR-2026-")
        # A raise afterwards changes nothing in the approved payslip.
        change_pay(employee.pk, CompensationInput(effective_from=date(2026, 11, 1),
                                                  salary=D(9000)))
        assert run.payslips.get().net == D(6000)
        assert run.payslips.get().snapshot["terms"]["salary"] == "6000.00"
        with pytest.raises(Conflict):
            runs.calculate_run(run.pk)
        lifecycle.record_payment(run.pk, lifecycle.PaymentInput(date(2026, 11, 1), "bank",
                                                              "TRF-1"))
        run.refresh_from_db()
        assert run.status == RunStatus.PAID and run.payment_reference == "TRF-1"
        with pytest.raises(Conflict):
            lifecycle.reverse_run(run.pk, "wrong")  # a paid run is corrected in a later run


def test_overlapping_regular_runs_skip_the_employee(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        first = _run()
        second = _run(scope="branch", scope_id=employee.branch_id)
        assert not second.payslips.exists()
        assert second.skipped[0]["employee_id"] == employee.pk
        runs.delete_draft(first.pk)
        runs.calculate_run(second.pk)
        assert second.payslips.count() == 1


def test_an_installment_is_never_taken_twice(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        loan = grant_loan(LoanInput(employee_id=employee.pk, granted_on=date(2026, 9, 20),
                                    amount=D(900), installments=3, first_month=date(2026, 10, 1)))
        run = _run()
        assert _lines(run.payslips.get())["installment"] == D(300)
        lifecycle.approve_run(run.pk)
        assert loan.installments.get(number=1).status == InstallmentStatus.PAID
        # An off-cycle run over the same days doesn't see it again.
        extra = runs.create_run(runs.RunInput(
            frequency="monthly", kind="off_cycle", start=date(2026, 10, 1),
            end=date(2026, 10, 31), reason="Bonus"))
        assert "installment" not in _lines(extra.payslips.get())
        # Reversing releases it: the installment is due again, and a new run takes it.
        lifecycle.reverse_run(run.pk, "Wrong overtime")
        assert loan.installments.get(number=1).status == InstallmentStatus.DUE
        assert not PaidSource.objects.filter(released=False).exists()
        again = _run()
        assert _lines(again.payslips.get())["installment"] == D(300)


def test_two_drafts_cant_both_pay_the_same_incentive(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        give_adjustment(AdjustmentInput(
            type_id=AdjustmentType.objects.filter(kind="incentive").first().pk,
            target=Target.employee(employee.pk), date=date(2026, 10, 10), method="fixed",
            quantity=D(500)), approve=True)
        regular = _run()
        off_cycle = runs.create_run(runs.RunInput(
            frequency="monthly", kind="off_cycle", start=date(2026, 10, 1),
            end=date(2026, 10, 31), reason="Bonus"))
        assert _lines(regular.payslips.get())["incentive"] == D(500)
        assert _lines(off_cycle.payslips.get()) == {"incentive": D(500)}
        lifecycle.approve_run(off_cycle.pk)
        # The regular draft is recalculated at approval: the incentive is already paid.
        lifecycle.approve_run(regular.pk)
        assert "incentive" not in _lines(regular.payslips.get())


def test_insurance_missing_blocks_approval_and_zero_doesnt(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        pay = employee.pay_history.get()
        pay.insured_salary = D(5000)
        pay.save()
        run = _run()
        slip = run.payslips.get()
        assert slip.blocking == 1 and slip.issues[0]["code"] == "insurance_missing"
        assert "insurance_employee" not in _lines(slip)
        with pytest.raises(DomainError):
            lifecycle.approve_run(run.pk)
        InsuranceRate.objects.create(effective_from=date(2026, 1, 1), employee_rate=D(0),
                                     employer_rate=D(0))
        lifecycle.approve_run(run.pk)  # 0 % is a deliberate setting
        assert run.payslips.get().net == D(6000)


def test_employee_and_employer_insurance_are_separate(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        pay = employee.pay_history.get()
        pay.insured_salary = D(20000)
        pay.save()
        InsuranceRate.objects.create(effective_from=date(2026, 1, 1), employee_rate=D(11),
                                     employer_rate=D("18.75"), max_insured=D(14500))
        slip = _run().payslips.get()
        lines = _lines(slip)
        assert lines["insurance_employee"] == D("1595.00")  # 11 % of the 14,500 cap
        assert slip.employer_cost == D("2718.75") and slip.net == D("4405.00")


def test_weekly_employees_have_their_own_runs(client_a, make_employee):
    weekly = make_employee(client_a, 1, salary=D(1400))
    monthly = make_employee(client_a, 2)
    with tenant_context(client_a.id):
        pay = weekly.pay_history.get()
        pay.pay_frequency = "weekly"
        pay.save()
        transport = PayItem.objects.create(code=1, name="Transport", kind="addition")
        give_items(AssignmentInput(item_id=transport.pk, target=Target.employee(weekly.pk),
                                   frequency="monthly", amount=D(310),
                                   starts_on=date(2026, 10, 1)))
        month_run = _run()
        assert set(month_run.payslips.values_list("employee_id", flat=True)) == {monthly.pk}
        week_run = _run(day=date(2026, 10, 7), frequency="weekly")
        slip = week_run.payslips.get()
        assert slip.employee_id == weekly.pk
        assert (week_run.period.start, week_run.period.end) == (date(2026, 10, 3),
                                                                date(2026, 10, 9))
        lines = _lines(slip)
        assert lines["salary"] == D(1400)
        assert lines["item"] == D(70)  # 7 of October's 31 days of 310


def test_what_a_run_paid_is_locked(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        run = _run()
        lifecycle.approve_run(run.pk)
        with pytest.raises(DomainError) as refused:
            change_pay(employee.pk, CompensationInput(effective_from=date(2026, 10, 20),
                                                      salary=D(7000)))
        assert refused.value.code == "PAYROLL_LOCKED"
        lifecycle.reverse_run(run.pk, "Raise missed")
        change_pay(employee.pk, CompensationInput(effective_from=date(2026, 10, 20),
                                                  salary=D(7000)))  # open again


def test_manual_lines_survive_recalculation(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        run = _run()
        manual_lines.add_manual_line(run.pk, manual_lines.ManualLineInput(
            employee_id=employee.pk, label="Correction for September", amount=D(250)))
        runs.calculate_run(run.pk)
        slip = run.payslips.get()
        assert slip.net == D(6250) and _lines(slip)["manual"] == D(250)
        run.refresh_from_db()
        assert run.net == D(6250)


def test_loans_are_repaid_when_their_last_installment_is_paid(client_a, make_employee):
    employee = make_employee(client_a)
    with tenant_context(client_a.id):
        loan = grant_loan(LoanInput(employee_id=employee.pk, granted_on=date(2026, 9, 20),
                                    amount=D(500), installments=1, first_month=date(2026, 10, 1)))
        lifecycle.approve_run(_run().pk)
        loan.refresh_from_db()
        assert loan.status == LoanStatus.SETTLED
