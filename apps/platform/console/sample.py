"""Development only: a whole company to try every screen on (manage.py create_sample). Where demo.py
is a small example, this has the size and the awkward cases of a real client: branches and
departments that closed, a department in several branches, every kind of pay, night shifts, people
who moved, left or came back, requests in every state, and months of payroll at each stage.

Written through the same services as the screens, as a trusted caller, so it obeys the same rules.
Only clock times are written directly: a device would, and there are thousands. Dates count back
from today, and the names and numbers are invented. The same company comes out every time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

from django.utils import timezone

from apps.adjustments.models import AdjustmentType
from apps.adjustments.services import batches as adjustments
from apps.attendance.models import DayKind, LeaveType, Punch, PunchSource
from apps.attendance.selectors import ScheduleHistory
from apps.attendance.services import approvals, entries, hourly, leave
from apps.compensation.models import PayItem
from apps.compensation.services import AssignmentInput, PayItemInput, give_items, save_pay_item
from apps.devices.models import Device
from apps.devices.services import devices
from apps.employees.models import Employee, Gender, MaritalStatus, MilitaryStatus, WageType
from apps.employees.selectors import BRANCH, DEPARTMENT, EMPLOYEE, Target
from apps.employees.services import employees
from apps.evaluations import services as evaluations
from apps.iam.catalog import MANAGER, VIEWER
from apps.iam.models import Role
from apps.iam.services import (
    MemberInput,
    RoleAssignmentInput,
    create_member,
    create_role,
    set_member_status,
    system_role_templates,
)
from apps.loans.services import advances, loans
from apps.mobile.services import access
from apps.org.models import Branch, Department, Position
from apps.org.services import (
    BranchInput,
    DepartmentInput,
    PositionInput,
    create_branch,
    save_department,
    save_position,
    set_branch_active,
    set_department_active,
)
from apps.payroll.services import lifecycle as payroll_lifecycle
from apps.payroll.services import runs as payroll
from apps.platform.console import demo
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from apps.policies.models import LatenessPolicy, OvertimePolicy, PublicHoliday

HEAD_OFFICE = "القاهرة - المركز الرئيسي"
FRIDAY, SATURDAY = 4, 5
BRANCHES = [  # code, name, phone, address
    (2, "الإسكندرية", "0345550102", "طريق الحرية، الإسكندرية"),
    (3, "الجيزة", "0235550103", "شارع الهرم، الجيزة"),
    (4, "المنصورة", "0505550104", "شارع الجمهورية، المنصورة"),
    (5, "أسيوط", "0885550105", "شارع يسري راغب، أسيوط"),
    (6, "طنطا", "0405550106", "شارع البحر، طنطا"),  # closed: has no one left in it
]
CLOSED_BRANCH = 6
OFFICE = (time(9), time(17), [FRIDAY, SATURDAY])
SHOP = (time(10), time(18), [FRIDAY])
STORE = (time(8), time(16), [FRIDAY])
NIGHT = (time(22), time(6), [FRIDAY])
DEPARTMENTS = [  # name, branch codes, shift, how many of the staff, positions: name and salary
    ("الإدارة العامة", (1,), OFFICE, 1, [("مدير عام", 32000), ("مساعد إداري", 9000)]),
    ("الموارد البشرية", (1,), OFFICE, 1,
     [("مدير موارد بشرية", 18000), ("أخصائي شؤون عاملين", 9500)]),
    ("الحسابات", (1, 2), OFFICE, 2, [("رئيس حسابات", 19000), ("محاسب", 10500)]),
    ("المبيعات", (1, 2, 3, 4, 5), SHOP, 6, [("مدير فرع", 17000), ("مندوب مبيعات", 7800)]),
    ("خدمة العملاء", (1, 2, 3), SHOP, 3, [("مشرف خدمة عملاء", 11000), ("موظف خدمة عملاء", 7000)]),
    ("المخازن", (1, 2, 4), STORE, 3, [("أمين مخزن", 8500), ("عامل مخزن", 6000)]),
    ("النقل", (1, 3), STORE, 2, [("سائق", 6800)]),
    ("الأمن", (1, 2, 3, 4, 5), NIGHT, 2, [("فرد أمن", 5800)]),
    ("تكنولوجيا المعلومات", (1,), OFFICE, 1, [("مهندس نظم", 16000), ("فني دعم", 8200)]),
]
OLD_DEPARTMENT = "المشتريات القديمة"  # deactivated: shows only with "Show inactive"
MEN = ["أحمد", "محمد", "محمود", "مصطفى", "عمر", "خالد", "يوسف", "إبراهيم", "حسن", "علي", "طارق",
       "كريم", "هاني", "سامح", "وليد", "شريف", "أيمن", "رامي", "عمرو", "إسلام"]
WOMEN = ["سارة", "منى", "نور", "هبة", "مريم", "دينا", "ريم", "ياسمين", "إيمان", "فاطمة", "آية",
         "نهى", "سلمى", "رانيا", "شيماء", "أميرة"]
FAMILIES = ["حسن", "عبد الله", "السيد", "إبراهيم", "فتحي", "سعيد", "عادل", "رمضان", "عثمان",
            "البنا", "الشريف", "منصور", "عبد الرحمن", "صالح", "زكي", "النجار"]
PAY_ITEMS = [  # code, name, kind, basis, taxable
    (1, "بدل انتقال", "addition", "per_day", True),
    (2, "بدل وجبة", "addition", "fixed", True),
    (3, "بدل سكن", "addition", "fixed", True),
    (4, "عمولة مبيعات", "addition", "fixed", True),
    (5, "زي العمل", "deduction", "fixed", False),
    (6, "اشتراك العلاج", "deduction", "fixed", False),
]


@dataclass(frozen=True)
class Window:
    """The months the company has been running for, ending yesterday."""

    today: date
    first: date  # the 1st of the earliest month
    month_ends: tuple[date, ...]  # the last day of each whole month, oldest first

    @property
    def yesterday(self) -> date:
        return self.today - timedelta(days=1)


def _window(months: int) -> Window:
    today = timezone.localdate()
    ends = []
    end = today.replace(day=1) - timedelta(days=1)
    for _ in range(months):
        ends.insert(0, end)
        end = end.replace(day=1) - timedelta(days=1)
    return Window(today, ends[0].replace(day=1), tuple(ends))


def seed_structure() -> None:
    created = {1: Branch.objects.get(code=1).pk}
    for code, name, phone, address in BRANCHES:
        created[code] = create_branch(BranchInput(code=code, name=name, phone=phone,
                                                  address=address)).pk
    for name, codes, _shift, _share, jobs in DEPARTMENTS:
        department = save_department(DepartmentInput(name, tuple(created[code] for code in codes)))
        for job, _salary in jobs:
            save_position(PositionInput(job, department.pk))
    old = save_department(DepartmentInput(OLD_DEPARTMENT, (created[1],)))
    set_department_active(old.pk, False)
    set_branch_active(created[CLOSED_BRANCH], False)


def seed_rules() -> None:
    for code, name, kind, basis, taxable in PAY_ITEMS:
        save_pay_item(PayItemInput(code=code, name=name, kind=kind, basis=basis, taxable=taxable))
    demo.seed_pay_rules()


def _card(chance: random.Random, code: int, person: dict) -> employees.EmployeeInput:
    woman = chance.random() < 0.35
    first = chance.choice(WOMEN if woman else MEN)
    born = date(chance.randint(1968, 2002), chance.randint(1, 12), chance.randint(1, 28))
    return employees.EmployeeInput(
        code=code, name=f"{first} {chance.choice(MEN)} {chance.choice(FAMILIES)}",
        gender=Gender.FEMALE if woman else Gender.MALE, birth_date=born,
        national_id=f"{2 if born.year < 2000 else 3}{born:%y%m%d}01{code:05d}9"[:14],
        phone=f"010{code:08d}", email=f"staff{code}@nile.example", address="القاهرة",
        marital_status=chance.choice(MaritalStatus.values), children=chance.randint(0, 3),
        military_status=MilitaryStatus.NOT_APPLICABLE if woman else MilitaryStatus.COMPLETED,
        qualification=chance.choice(["بكالوريوس تجارة", "ليسانس حقوق", "دبلوم فني", "هندسة"]),
        insurance_number=f"{code:09d}" if person["insured"] else "",
        insured_from=person["hired"] if person["insured"] else None,
        **{name: person[name] for name in ("branch_id", "department_id", "position_id")},
        hired_on=person["hired"], job_title=person["job"])


def _pay(code: int, salary: int, insured: bool) -> employees.CompensationInput:
    """Most are paid a monthly salary; some by the day or the hour each week, some every two."""
    if code % 13 == 0:
        return employees.CompensationInput(None, D(round(salary / 22)), WageType.DAILY, "weekly",
                                           permission_hours=D(4))
    if code % 17 == 0:
        return employees.CompensationInput(None, D(round(salary / 176)), WageType.HOURLY, "weekly",
                                           permission_hours=D(4))
    return employees.CompensationInput(
        None, D(salary), pay_frequency="biweekly" if code % 19 == 0 else "monthly",
        insured_salary=min(D(salary), D(14500)) if insured else None, permission_hours=D(4))


def _places() -> list[tuple]:
    """Each department in each of its branches, as often as it has staff there."""
    places = []
    branches = dict(Branch.objects.values_list("code", "pk"))
    for name, codes, shift, share, jobs in DEPARTMENTS:
        department = Department.objects.get(name=name)
        titles = list(Position.objects.filter(department=department).order_by("pk"))
        for code in codes:
            for turn in range(share):
                index = min(turn, len(jobs) - 1) if len(jobs) > 1 else 0
                places.append((branches[code], department.pk, shift, titles[index], jobs[index][1]))
    return places


def seed_employees(count: int, window: Window, chance: random.Random) -> list[Employee]:
    places = _places()
    lateness = LatenessPolicy.objects.first()
    overtime = OvertimePolicy.objects.first()
    staff = []
    for code in range(1, count + 1):
        branch, department, (start, end, days_off), title, salary = places[code % len(places)]
        insured = code % 7 != 0
        hired = window.first - timedelta(days=chance.randint(30, 2800))
        person = {"branch_id": branch, "department_id": department, "position_id": title.pk,
                  "job": title.name, "hired": hired, "insured": insured}
        if code % 29 == 0:  # no department yet: the amber node of the structure page
            person.update(department_id=None, position_id=None)
        staff.append(employees.create_employee(
            _card(chance, code, person),
            _pay(code, salary + chance.randrange(0, 1500, 100), insured),
            employees.ScheduleInput(
                None, start, end, days_off, lateness.pk, overtime.pk if code % 3 else None,
                early_leave_minutes=10)))
    return staff


def _steady(staff: list[Employee], window: Window) -> list[Employee]:
    """Monthly employees with nothing unusual, for the cases below to pick from."""
    return [person for person in staff if person.left_on is None and person.hired_on < window.first
            and person.pay_history.filter(pay_frequency="monthly", wage_type="fixed").exists()]


def seed_changes(staff: list[Employee], window: Window, chance: random.Random) -> None:
    """A company's history: raises, new hours, transfers, people leaving and coming back."""
    picks = chance.sample(_steady(staff, window), min(16, len(_steady(staff, window))))
    raised, shifted, moved, gone = picks[:6], picks[6:8], picks[8:12], picks[12:16]
    for person in raised:
        pay = person.pay_history.order_by("-effective_from").first()
        employees.change_pay(person.pk, employees.CompensationInput(
            window.first + timedelta(days=14), (pay.salary * D("1.12")).quantize(D(1)),
            insured_salary=pay.insured_salary, permission_hours=pay.permission_hours,
            note="زيادة سنوية"))
    for person in shifted:
        row = person.schedules.order_by("-effective_from").first()
        employees.change_schedule(person.pk, employees.ScheduleInput(
            window.first + timedelta(days=20), time(11), time(19), row.days_off,
            row.lateness_policy_id, row.overtime_policy_id, note="تغيير الوردية"))
    open_branches = Branch.objects.filter(is_active=True).exclude(code=1).order_by("code")
    for person, branch in zip(moved, open_branches, strict=False):
        place = Department.objects.filter(placements__branch=branch, is_active=True).first()
        employees.change_assignment(person.pk, employees.AssignmentInput(
            window.first + timedelta(days=9), branch.pk, place.pk if place else None,
            person.job_title, person.position_id, note="نقل إلى فرع آخر"))
    for person, reason in zip(gone[:-1], ["استقالة", "إنهاء عقد", "تقاعد"], strict=False):
        employees.end_employment(person.pk, window.today - timedelta(days=chance.randint(15, 25)),
                                 reason)
    if gone:  # left for a while, then came back
        back = gone[-1]
        employees.end_employment(back.pk, window.first - timedelta(days=20), "استقالة")
        employees.rehire(back.pk, employees.AssignmentInput(
            window.first + timedelta(days=5), back.branch_id, back.department_id, back.job_title,
            back.position_id, note="عودة للعمل"))


def seed_new_hires(staff: list[Employee], window: Window, chance: random.Random) -> None:
    """Joined this period, and one who starts next week: not on anything yet."""
    place = Branch.objects.get(code=2)
    department = Department.objects.get(name="المبيعات")
    days = [window.today - timedelta(days=d) for d in (25, 12)] + [window.today + timedelta(days=7)]
    for offset, hired in enumerate(days, start=len(staff) + 1):
        staff.append(employees.create_employee(
            _card(chance, offset, {"branch_id": place.pk, "department_id": department.pk,
                                   "position_id": None, "job": "مندوب مبيعات تحت التدريب",
                                   "hired": hired, "insured": False}),
            employees.CompensationInput(None, D(6500), permission_hours=D(4)),
            employees.ScheduleInput(None, *SHOP[:2], SHOP[2])))


def seed_leave(staff: list[Employee], window: Window, chance: random.Random) -> dict:
    """Requests in every state, and hours off. Returns {employee id: days away from work}."""
    away: dict[int, set[date]] = {}
    types = list(LeaveType.objects.order_by("code"))
    holidays = set(PublicHoliday.objects.values_list("date", flat=True))
    people = _steady(staff, window)
    for index, person in enumerate(people[: len(people) // 2]):
        row = person.schedules.order_by("-effective_from").first()
        length = chance.randint(1, 3)
        day = window.yesterday - timedelta(days=chance.randint(length + 4, 45))
        days = [day + timedelta(days=n) for n in range(length)]
        if day < window.first or any(d.weekday() in row.days_off or d in holidays for d in days):
            continue
        request = leave.request_leave(leave.LeaveRequestInput(
            person.pk, types[index % len(types)].pk, days[0], days[-1],
            chance.choice(["ظرف عائلي", "إجازة مرضية", "سفر", "مناسبة"])))
        if index % 8 == 6:
            leave.decide_leave(request.pk, approvals.REJECT, note="ضغط العمل")
        else:
            leave.decide_leave(request.pk, approvals.APPROVE)
            away.setdefault(person.pk, set()).update(days)
            if index % 8 == 7:
                leave.decide_leave(request.pk, approvals.CANCEL, note="ألغى الموظف الطلب")
                away[person.pk].difference_update(days)
    soon = window.today + timedelta(days=4)
    for person in people[-5:]:  # waiting for a manager
        row = person.schedules.order_by("-effective_from").first()
        if soon.weekday() not in row.days_off and soon not in holidays:
            leave.request_leave(leave.LeaveRequestInput(person.pk, types[0].pk, soon, soon, "سفر"))
    for person in people[len(people) // 2:][:8]:
        row = person.schedules.order_by("-effective_from").first()
        day = window.month_ends[-1] - timedelta(days=chance.randint(1, 10))
        if (day.weekday() not in row.days_off and day not in holidays
                and row.starts_at < row.ends_at):
            start = datetime.combine(day, row.starts_at) + timedelta(hours=2)
            hourly.record_hourly_leave(hourly.HourlyLeaveInput(
                person.pk, day, start.time(), (start + timedelta(hours=1)).time(), "مشوار بنكي"),
                approve=True)
    return away


def seed_punches(staff: list[Employee], window: Window, away: dict, chance: random.Random) -> int:
    """Clock times up to yesterday: each person has their habits. In the last month a few forgot
    to clock out, which is what a payroll review has to catch."""
    zone = timezone.get_current_timezone()
    holidays = set(PublicHoliday.objects.values_list("date", flat=True))
    last_month = window.month_ends[-1].replace(day=1)
    rows = []
    total_days = (window.yesterday - window.first).days + 1
    for person in staff:
        history = ScheduleHistory(person.schedules.all())
        latest = chance.choice([0, 3, 5, 12, 25, 45])
        for offset in range(total_days):
            day = window.first + timedelta(days=offset)
            row = history.on(day)
            left = person.left_on is not None and day > person.left_on
            if (row is None or left or day < person.hired_on or day.weekday() in row.days_off
                    or day in holidays or day in away.get(person.pk, ())
                    or chance.random() < 0.03):
                continue
            came = (datetime.combine(day, row.starts_at, tzinfo=zone)
                    + timedelta(minutes=chance.randint(-5, latest)))
            went = datetime.combine(day, row.ends_at, tzinfo=zone)
            if went <= came:
                went += timedelta(days=1)  # a night shift ends the next morning
            went += timedelta(minutes=chance.choice([-20, 0, 0, 0, 10, 35, 90]))
            rows.append(Punch(employee=person, at=came, source=PunchSource.DEVICE))
            if not (day >= last_month and chance.random() < 0.01):
                rows.append(Punch(employee=person, at=went, source=PunchSource.DEVICE))
    Punch.objects.bulk_create(rows, batch_size=2000)
    return len(rows)


def seed_days(staff: list[Employee], window: Window) -> None:
    """A manager's word on some days: an excused absence, a corrected day."""
    day = window.first + timedelta(days=3)
    for person in _steady(staff, window)[:4]:
        row = person.schedules.order_by("-effective_from").first()
        if day.weekday() not in row.days_off:
            entries.set_day(person.pk, day, entries.DayEntryInput(DayKind.EXCUSED, note="بعذر طبي"))


def seed_pay_entries(staff: list[Employee], window: Window) -> None:
    """Allowances for a branch, a department and one person; incentives and penalties at each
    stage; advances; loans part repaid."""
    head = Branch.objects.get(code=1)
    sales = Department.objects.get(name="المبيعات")
    items = {item.code: item for item in PayItem.objects.all()}
    people = _steady(staff, window)
    start = window.first
    give_items(AssignmentInput(items[1].pk, Target(BRANCH, head.pk), "period", D(40), start,
                               note="انتقال يومي"))
    give_items(AssignmentInput(items[2].pk, Target(DEPARTMENT, sales.pk), "monthly", D(500), start))
    give_items(AssignmentInput(items[3].pk, Target(EMPLOYEE, people[0].pk), "monthly", D(1500),
                               start))
    give_items(AssignmentInput(items[6].pk, Target(EMPLOYEE, people[1].pk), "monthly", D(200),
                               start))
    incentive = AdjustmentType.objects.get(kind="incentive", code=1).pk
    penalty = AdjustmentType.objects.get(kind="penalty", code=1).pk
    day = window.month_ends[-1] - timedelta(days=2)
    adjustments.give(adjustments.AdjustmentInput(incentive, Target(EMPLOYEE, people[2].pk), day,
                                                 "percent", D(10), "أفضل موظف"), approve=True)
    adjustments.give(adjustments.AdjustmentInput(incentive, Target(DEPARTMENT, sales.pk), day,
                                                 "fixed", D(750), "تحقيق المستهدف"), approve=True)
    adjustments.give(adjustments.AdjustmentInput(penalty, Target(EMPLOYEE, people[3].pk), day,
                                                 "hours", D(4), "مخالفة التعليمات"), approve=True)
    adjustments.give(adjustments.AdjustmentInput(  # a draft, to approve
        penalty, Target(BRANCH, Branch.objects.get(code=2).pk), window.today, "hours", D(1),
        "تأخير جماعي عن الجرد"))
    mistake = adjustments.give(adjustments.AdjustmentInput(
        incentive, Target(EMPLOYEE, people[4].pk), window.today, "fixed", D(1000), "إنجاز عمل"),
        approve=True)
    adjustments.cancel(mistake.pk, "أُدخل بالخطأ")
    for person, amount in zip(people[5:9], (500, 800, 1000, 1500), strict=False):
        advances.give_advance(advances.AdvanceInput(person.pk, day, D(amount), "سلفة شخصية"))
    for person, (amount, months) in zip(people[9:13], ((6000, 6), (12000, 12), (3000, 3),
                                                       (9000, 9)), strict=False):
        loans.grant_loan(loans.LoanInput(person.pk, start, D(amount), months, start, "قرض شخصي"))
    spare = loans.grant_loan(loans.LoanInput(people[13].pk, day, D(2000), 2, window.today, "قرض"))
    loans.cancel_loan(spare.pk)


def _settle(run, *, approve: bool, pay: bool, paid_on: date) -> None:
    if not approve or not run.payslips.exists() or run.payslips.filter(blocking__gt=0).exists():
        return  # one with a problem waits for a person: that is what the screen is for
    payroll_lifecycle.approve_run(run.pk)
    if pay:
        payroll_lifecycle.record_payment(run.pk, payroll_lifecycle.PaymentInput(
            paid_on, "تحويل بنكي", f"NILE-{run.pk:04d}"))


def seed_payroll(window: Window) -> None:
    """Paid, approved and draft months. The last month stays a draft, with its problems showing.
    People paid by the week or two weeks have their runs too, one of them reversed."""
    last = len(window.month_ends) - 1
    for index, end in enumerate(window.month_ends):
        run = payroll.create_run(payroll.RunInput("monthly", day=end))
        _settle(run, approve=index < last, pay=index < last - 1, paid_on=end + timedelta(days=2))
    weeks = 2 + 2 * len(window.month_ends)
    for back in range(weeks, 0, -2):
        day = window.today - timedelta(weeks=back)
        run = payroll.create_run(payroll.RunInput("weekly", day=day))
        _settle(run, approve=back > 2, pay=back > 4, paid_on=day + timedelta(weeks=1))
        run.refresh_from_db()
        if back == 4 and run.status == "approved":  # only a run not paid yet can be reversed
            payroll_lifecycle.reverse_run(run.pk, "خطأ في أيام الحضور")
    for back in (5, 3):
        day = window.today - timedelta(weeks=back)
        run = payroll.create_run(payroll.RunInput("biweekly", day=day))
        _settle(run, approve=back == 5, pay=True, paid_on=day + timedelta(weeks=1))


def seed_evaluations(staff: list[Employee], window: Window, chance: random.Random) -> None:
    year = window.today.year - 1
    notes = ["ملتزم ومتعاون مع الفريق.", "يحتاج إلى تطوير مهارات التواصل.",
             "أداء ممتاز ومؤهل للترقية.", "يلتزم بالمواعيد ويؤدي عمله بدقة."]
    for person in _steady(staff, window)[:25]:
        if person.hired_on.year <= year:
            evaluations.save(evaluations.EvaluationInput(
                person.pk, year, date(year, 12, 28), chance.choice(notes), chance.choice(notes)))


def seed_people_who_sign_in(slug: str, password: str) -> list[tuple[str, str]]:
    """Who to sign in as, to see what each kind of member sees."""
    branches = dict(Branch.objects.values_list("code", "pk"))
    roles = dict(Role.objects.values_list("code", "pk"))
    allowed = system_role_templates()[MANAGER][2]
    accounts = create_role("محاسب الرواتب", "يراجع الرواتب والسلف ولا يعدل بيانات الموظفين", [
        code for code in allowed
        if code.startswith(("payroll.", "loans.", "adjustments.", "employees.salary.read"))
        or code == "employees.employee.view"])
    members = [  # username, name, role, branches, what they show
        ("hr", "هبة الموارد البشرية", roles[MANAGER], None, "Manager, every branch"),
        ("alex", "كريم مدير الفرع", roles[MANAGER], (branches[2], branches[3]),
         "Manager of two branches"),
        ("accounts", "نهى المحاسبة", accounts.pk, None, "A custom role"),
        ("viewer", "طارق المراجع", roles[VIEWER], None, "Read only"),
        ("former", "سامح السابق", roles[VIEWER], None, "Suspended: can't sign in"),
    ]
    shown = []
    for username, name, role, scope, what in members:
        member = create_member(MemberInput(
            username, name, email=f"{username}@{slug}.test",
            roles=(RoleAssignmentInput(role, scope),)), password)
        shown.append((username, what))
        if username == "former":
            set_member_status(member.pk, "suspended")
    return shown


def seed_integrations(tenant, staff: list[Employee], window: Window, password: str) -> str:
    """The mobile app, fingerprint devices and WhatsApp, as demo.py does. Returns the app login."""
    for key in ("mobile_app", "zk_devices", "whatsapp"):
        TenantFeature.objects.update_or_create(tenant=tenant, key=key, defaults={"enabled": True})
    features.forget(tenant.pk)
    if not Device.objects.exists():
        for code, serial, name in ((1, 1, "البوابة الرئيسية"), (2, 2, "مدخل الإسكندرية")):
            devices.save_device(devices.DeviceInput(f"{tenant.slug.upper()}-ZK-{serial:04d}", name,
                                                    Branch.objects.get(code=code).pk))
    person = _steady(staff, window)[-1]
    access.give_login(person.pk, f"{tenant.slug}app", password)
    return f"{tenant.slug}app"


def seed(tenant, password: str, *, people: int = 120, months: int = 3,
         say=lambda text: None) -> dict:
    """Everything, in the order a company would have done it. Run in the tenant's context and
    time zone. Payroll comes last: an approved period can't be changed."""
    chance = random.Random(2026)
    window = _window(months)
    say("Branches, departments and positions")
    seed_structure()
    say("Pay rules")
    seed_rules()
    say(f"{people} employees")
    staff = seed_employees(people, window, chance)
    say("Raises, transfers, leavers and new hires")
    seed_changes(staff, window, chance)
    seed_new_hires(staff, window, chance)
    for person in staff:
        person.refresh_from_db()
    say("Leave")
    away = seed_leave(staff, window, chance)
    say("Clock times")
    punches = seed_punches(staff, window, away, chance)
    seed_days(staff, window)
    say("Allowances, incentives, advances and loans")
    seed_pay_entries(staff, window)
    say("Evaluations, users and integrations")
    seed_evaluations(staff, window, chance)
    logins = seed_people_who_sign_in(tenant.slug, password)
    app = seed_integrations(tenant, staff, window, password)
    say("Payroll")
    seed_payroll(window)
    return {"employees": len(staff), "punches": punches, "logins": logins, "app": app}
