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

from apps.attendance import hourly, leave
from apps.attendance.models import LeaveType, Punch, PunchSource
from apps.attendance.selectors import ScheduleHistory
from apps.compensation.services import PayItemInput, save_pay_item
from apps.employees import services as employees
from apps.employees.models import Employee
from apps.org.models import Branch, Department
from apps.org.services import DepartmentInput, save_department
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
    for code, name in DEPARTMENTS:
        save_department(DepartmentInput(code=code, name=name))
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
    departments = dict(Department.objects.values_list("code", "pk"))
    lateness = LatenessPolicy.objects.first()
    overtime = OvertimePolicy.objects.first()
    for (code, name, branch, department, job, hired, salary, (start, end), days_off, late,
         extra) in people:
        if branch not in branches:
            continue
        person = employees.create_employee(
            employees.EmployeeInput(code=code, name=name, branch_id=branches[branch],
                                    department_id=departments.get(department), job_title=job,
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


def seed_attendance(days: int = 14) -> None:
    """Two weeks of clock times up to yesterday: mostly on time, some late, an absence, a leave
    request approved and one waiting, and an hour of hourly leave."""
    if Punch.objects.exists():
        return
    zone = timezone.get_current_timezone()
    today = timezone.localdate()
    chance = random.Random(7)  # the same demo every time
    people = list(Employee.objects.exclude(left_on__lt=today - timedelta(days=days)))
    for person in people:
        history = ScheduleHistory(person.schedules.all())
        for back in range(days, 0, -1):
            day = today - timedelta(days=back)
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
    if annual is None or len(people) < 3:
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
