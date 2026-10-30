"""Development only: example pay set-up and employees for the demo clients (manage.py
create_demo). Written through the same services as the screens, as a trusted caller.

The tax brackets and insurance rates are examples to click through, not legal advice: a real
client enters the ones that apply to it.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

from django.utils import timezone

from apps.adjustments import services as adjustments
from apps.adjustments.models import AdjustmentType
from apps.attendance import hourly, leave
from apps.attendance.models import LeaveRequest, LeaveType, Punch, PunchSource
from apps.attendance.selectors import ScheduleHistory
from apps.compensation.models import PayItem
from apps.compensation.services import AssignmentInput, PayItemInput, give_items, save_pay_item
from apps.employees import services as employees
from apps.employees.models import Employee
from apps.employees.targets import BRANCH, DEPARTMENT, EMPLOYEE, Target
from apps.loans import advances
from apps.loans import services as loans
from apps.loans.models import Loan
from apps.org.models import Branch, Department
from apps.org.services import DepartmentInput, save_department
from apps.payroll import services as payroll
from apps.payroll.models import PayrollRun
from apps.policies import services as policies
from apps.policies.domain.bands import Band
from apps.policies.domain.tax import Bracket
from apps.policies.models import LatenessPolicy, OvertimePolicy

FRIDAY, SATURDAY = 4, 5

DEPARTMENTS = [(1, "Administration"), (2, "Sales"), (3, "Warehouse")]
PAY_ITEMS = [  # code, name, kind, basis, taxable
    (1, "Transport allowance", "addition", "per_day", True),
    (2, "Meal allowance", "addition", "fixed", True),
    (3, "Uniform", "deduction", "fixed", False),
]
HOLIDAYS = [(date(2026, 1, 7), "Coptic Christmas"), (date(2026, 1, 25), "Revolution Day"),
            (date(2026, 4, 25), "Sinai Liberation Day"), (date(2026, 5, 1), "Labour Day"),
            (date(2026, 7, 23), "Revolution Day (July)"), (date(2026, 10, 6), "Armed Forces Day")]
# code, name, branch (code), department (code), job, hired, salary, shift, days off, late, ot
PEOPLE = [
    (1, "Ahmed Hassan", 1, 1, "Accountant", date(2023, 3, 1), D(9000), (9, 17),
     [FRIDAY, SATURDAY], True, False),
    (2, "Sara Mahmoud", 1, 1, "HR officer", date(2024, 1, 15), D(8000), (9, 17),
     [FRIDAY, SATURDAY], True, False),
    (3, "Omar Khaled", 1, 2, "Sales representative", date(2022, 6, 1), D(7000), (10, 18),
     [FRIDAY], True, True),
    (4, "Mona Adel", 2, 2, "Branch sales lead", date(2021, 9, 1), D(11000), (10, 18),
     [FRIDAY], True, True),
    (5, "Youssef Ibrahim", 2, 3, "Storekeeper", date(2024, 5, 1), D(6000), (8, 16),
     [FRIDAY], True, True),
    (6, "Hany Samir", 2, 3, "Night guard", date(2025, 2, 1), D(5500), (22, 6),
     [FRIDAY], False, False),
]


def seed_pay_setup() -> None:
    if Department.objects.exists():
        return
    for branch_id in Branch.objects.filter(is_active=True).values_list("pk", flat=True):
        for code, name in DEPARTMENTS:
            save_department(DepartmentInput(branch_id=branch_id, code=code, name=name))
    for code, name, kind, basis, taxable in PAY_ITEMS:
        save_pay_item(PayItemInput(code=code, name=name, kind=kind, basis=basis,
                                   taxable=taxable))
    policies.save_lateness_policy(policies.BandedPolicyInput(
        name="Standard lateness", minutes=10,
        bands=[Band(11, 30, D("0.5")), Band(31, 60, D(1)), Band(61, 120, D(2))]))
    policies.save_overtime_policy(policies.BandedPolicyInput(
        name="Standard overtime", minutes=15))
    policies.save_tax_table(policies.TaxTableInput(
        effective_from=date(2025, 1, 1), annual_exemption=D(20000), note="Example brackets",
        brackets=[Bracket(D(40000), D(0)), Bracket(D(55000), D(10)), Bracket(D(70000), D(15)),
                  Bracket(D(200000), D(20)), Bracket(D(400000), D("22.5")),
                  Bracket(None, D(25))]))
    policies.save_insurance_rate(policies.InsuranceRateInput(
        effective_from=date(2025, 1, 1), employee_rate=D(11), employer_rate=D("18.75"),
        min_insured=D(2300), max_insured=D(14500), note="Example rates"))
    for day, name in HOLIDAYS:
        policies.save_holiday(policies.HolidayInput(date=day, name=name))


def seed_employees(people=PEOPLE) -> None:
    if Employee.objects.exists():
        return
    branches = dict(Branch.objects.values_list("code", "pk"))
    departments = {(branch_id, code): pk for branch_id, code, pk
                   in Department.objects.values_list("branch_id", "code", "pk")}
    lateness = LatenessPolicy.objects.first()
    overtime = OvertimePolicy.objects.first()
    for (code, name, branch, department, job, hired, salary, (start, end), days_off, late,
         extra) in people:
        if branch not in branches:
            continue
        person = employees.create_employee(
            employees.EmployeeInput(code=code, name=name, branch_id=branches[branch],
                                    department_id=departments.get((branches[branch], department)),
                                    job_title=job,
                                    hired_on=hired, phone=f"010{code:08d}"),
            employees.CompensationInput(effective_from=None, salary=salary,
                                        insured_salary=min(salary, D(14500))),
            employees.ScheduleInput(
                effective_from=None, starts_at=time(start), ends_at=time(end), days_off=days_off,
                lateness_policy_id=lateness.pk if late and lateness else None,
                overtime_policy_id=overtime.pk if extra and overtime else None))
        if code == 1:  # a raise, to show pay history
            employees.change_pay(person.pk, employees.CompensationInput(
                effective_from=date(2025, 7, 1), salary=salary + D(1500),
                insured_salary=salary + D(1500), note="Yearly raise"))
        if code == 2:  # someone who left
            employees.end_employment(person.pk, date(2026, 6, 30), "Resigned")


def seed_attendance(days: int | None = None) -> None:
    """Clock times from the 1st of last month (or `days` back) up to yesterday, so both months
    can be paid: mostly on time, some late, an absence, a leave request approved and one
    waiting, and an hour of hourly leave. Days that already have clock times are kept."""
    zone = timezone.get_current_timezone()
    today = timezone.localdate()
    if days is None:
        days = (today - (today.replace(day=1) - timedelta(days=1)).replace(day=1)).days
    chance = random.Random(7)  # the same demo every time
    people = list(Employee.objects.exclude(left_on__lt=today - timedelta(days=days)))
    for person in people:
        history = ScheduleHistory(person.schedules.all())
        clocked = {at.astimezone(zone).date()
                   for at in Punch.objects.filter(employee=person).values_list("at", flat=True)}
        for back in range(days, 0, -1):
            day = today - timedelta(days=back)
            if day in clocked:
                continue
            row = history.on(day)
            if row is None or day.weekday() in row.days_off or chance.random() < 0.08:
                continue  # a day off, or absent
            late = chance.choice([0, 0, 0, 2, 5, 12, 25, 40])
            came = datetime.combine(day, row.starts_at, tzinfo=zone) + timedelta(minutes=late)
            left = datetime.combine(day, row.ends_at, tzinfo=zone)
            if left <= came:
                left += timedelta(days=1)
            left += timedelta(minutes=chance.choice([-15, 0, 0, 5, 30, 75]))
            for moment in (came, left):
                Punch.objects.get_or_create(employee=person, at=moment,
                                            defaults={"source": PunchSource.DEVICE})
    annual = LeaveType.objects.filter(uses_annual_balance=True).first()
    if annual is None or len(people) < 3 or LeaveRequest.objects.exists():
        return
    soon = today + timedelta(days=7)
    leave.request_leave(leave.LeaveRequestInput(
        employee_id=people[0].pk, leave_type_id=annual.pk, start_date=today - timedelta(days=3),
        end_date=today - timedelta(days=3), reason="Family visit"), approve=True)
    leave.request_leave(leave.LeaveRequestInput(
        employee_id=people[2].pk, leave_type_id=annual.pk, start_date=soon,
        end_date=soon + timedelta(days=2), reason="Travel"))
    for person in people[:2]:
        pay = person.pay_history.order_by("-effective_from").first()
        pay.permission_hours = D(4)
        pay.save(update_fields=["permission_hours"])
    hourly.record_hourly_leave(hourly.HourlyLeaveInput(
        employee_id=people[1].pk, work_date=today - timedelta(days=2), starts_at=time(13),
        ends_at=time(14), reason="Bank errand"), approve=True)


def seed_pay_entries() -> None:
    """This month's allowances for the head office, an incentive, a lateness penalty for a
    department, an advance and a loan."""
    if Loan.objects.exists():
        return
    today = timezone.localdate()
    people = list(Employee.objects.exclude(left_on__lt=today).order_by("code"))
    transport = PayItem.objects.filter(code=1).first()
    meals = PayItem.objects.filter(code=2).first()
    head = Branch.objects.filter(code=1).first()
    seller = (Employee.objects.filter(department__code=2).exclude(left_on__lt=today)
              .select_related("department").first())
    sales = seller.department if seller else None
    if not (people and transport and meals and head):
        return
    give_items(AssignmentInput(item_id=transport.pk, target=Target(BRANCH, head.pk),
                               frequency="period", amount=D(40),
                               starts_on=today.replace(day=1), note="Daily transport"))
    if sales and Employee.objects.filter(department=sales).exclude(left_on__lt=today).exists():
        give_items(AssignmentInput(item_id=meals.pk, target=Target(DEPARTMENT, sales.pk),
                                   frequency="monthly", amount=D(500),
                                   starts_on=today.replace(day=1)))
        adjustments.give(adjustments.AdjustmentInput(
            type_id=AdjustmentType.objects.get(kind="penalty", code=1).pk,
            target=Target(DEPARTMENT, sales.pk), date=today, method="hours",
            quantity=D(2), reason="Late for the stock count"))  # left a draft, to approve
    adjustments.give(adjustments.AdjustmentInput(
        type_id=AdjustmentType.objects.get(kind="incentive", code=1).pk,
        target=Target(EMPLOYEE, people[0].pk), date=today, method="percent", quantity=D(10),
        reason="Closed the quarter early"), approve=True)
    advances.give_advance(advances.AdvanceInput(employee_id=people[-1].pk, date=today,
                                                amount=D(1000), reason="Rent"))
    loans.grant_loan(loans.LoanInput(employee_id=people[1 if len(people) > 1 else 0].pk,
                                     granted_on=today, amount=D(6000), installments=6,
                                     first_month=today, reason="Car repair"))


def seed_payroll() -> None:
    """Last month's run approved and paid; this month's and this week's as drafts to review."""
    if PayrollRun.objects.exists():
        return
    today = timezone.localdate()
    last_month = today.replace(day=1) - timedelta(days=1)
    guard = Employee.objects.filter(code=6).first()
    if guard is not None and guard.left_on is None:  # paid every week, to show weekly runs
        employees.change_pay(guard.pk, employees.CompensationInput(
            effective_from=last_month.replace(day=1), salary=D(1300), pay_frequency="weekly",
            insured_salary=D(5500), note="Paid weekly from now on"))
    paid = payroll.create_run(payroll.RunInput(frequency="monthly", day=last_month))
    if paid.payslips.exists() and not paid.payslips.filter(blocking__gt=0).exists():
        payroll.approve_run(paid.pk)
        payroll.record_payment(paid.pk, payroll.PaymentInput(
            paid_on=today.replace(day=1), method="Bank transfer", reference="Demo"))
    payroll.create_run(payroll.RunInput(frequency="monthly", day=today))
    payroll.create_run(payroll.RunInput(frequency="weekly", day=today - timedelta(days=7)))


def seed_integrations(tenant, password: str) -> None:
    """The demo client tries the phase 6 integrations: the mobile app (one employee has a login),
    a fingerprint device (its serial is free to use with a real one), and WhatsApp (the console
    in development: nothing leaves the machine)."""
    from apps.devices import services as devices
    from apps.devices.models import Device
    from apps.mobile import access

    from . import features
    from .models import TenantFeature

    for key in ("mobile_app", "zk_devices", "whatsapp"):
        TenantFeature.objects.update_or_create(tenant=tenant, key=key,
                                               defaults={"enabled": True})
    features.forget(tenant.pk)
    head = Branch.objects.get(code=1)
    if not Device.objects.exists():
        devices.save_device(devices.DeviceInput("DEMO-ZK-0001", "Main gate", head.pk))
    first = Employee.objects.filter(code=1, member__isnull=True).first()
    if first is not None:
        access.give_login(first.pk, "ahmed", password)


def seed_evaluations() -> None:
    """Last year's evaluation of the first two employees."""
    from apps.evaluations import services as evaluations
    from apps.evaluations.models import Evaluation

    if Evaluation.objects.exists():
        return
    year = timezone.localdate().year - 1
    notes = [("Reliable and on time; trains the new staff.", "Ready to lead the team."),
             ("Good with customers.", "Needs to keep the stock sheets up to date.")]
    for person, (first, second) in zip(Employee.objects.order_by("code")[:2], notes,
                                       strict=False):
        evaluations.save(evaluations.EvaluationInput(person.pk, year, date(year, 12, 28),
                                                     note_1=first, note_2=second))
