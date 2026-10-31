"""Employee pages. They read and render; every save goes to the JSON API (apps/employees/api)."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core.errors import AppError
from apps.core.history import in_effect
from apps.core.import_page import ImportPage, import_page, template_download
from apps.core.listing import Choice, ListQuery
from apps.employees import imports
from apps.employees.models import (
    Compensation,
    Gender,
    MaritalStatus,
    MilitaryStatus,
    PayFrequency,
    WageType,
    Weekday,
)
from apps.employees.web.targets import group_page
from apps.iam.authz import permission_required
from apps.org.models import Branch
from apps.org.selectors import visible_departments
from apps.platform.tenants.limits import is_app_login
from apps.policies.models import LatenessPolicy, OvertimePolicy

from .. import selectors
from ..permissions import MANAGE, SALARY_MANAGE, SALARY_READ, VIEW

# Saturday first: the working week of the clients this was built for.
WEEK = [Weekday.SATURDAY, Weekday.SUNDAY, Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY,
        Weekday.THURSDAY, Weekday.FRIDAY]
STATUSES = [("active", _lazy("Working")), ("left", _lazy("Left")), ("all", _lazy("All"))]


def _by_status(queryset, value):
    today = timezone.localdate()
    if value == "active":
        return queryset.exclude(left_on__lt=today)
    if value == "left":
        return queryset.filter(left_on__lt=today)
    return queryset


@permission_required(VIEW)
def employees(request):
    departments = list(visible_departments(request.actor, VIEW))
    found = ListQuery(
        request, permission=VIEW, search=("name", "code", "phone", "job_title"),
        search_label=_("Name, code, phone or job"), date_field="",
        choices=[Choice("department", _("Department"), [("", _("All departments"))]
                        + [(d.pk, d.label) for d in departments], "department_id",
                        depends_on="branch", parents={d.pk: d.branch_id for d in departments}),
                 Choice("status", _("Status"), STATUSES, apply=_by_status, value="active")])
    rows = found.apply(selectors.visible_employees(request.actor).select_related(
        "branch", "department"))
    return render(request, "employees/employees.html", {
        "filters": found, "page": found.page(rows.order_by("code")),
        "can_import": request.actor.can("employees.employee.import"),
    })


def _choices(request) -> dict:
    actor = request.actor
    allowed = actor.branch_ids(MANAGE)
    branches = Branch.objects.filter(is_active=True).order_by("code")
    if allowed is not None:
        branches = branches.filter(pk__in=allowed)
    return {
        "branches": branches,
        "departments": visible_departments(actor, MANAGE).filter(is_active=True),
        "lateness_policies": (LatenessPolicy.objects.filter(is_active=True)
                              if actor.can("policies.lateness.view") else []),
        "overtime_policies": (OvertimePolicy.objects.filter(is_active=True)
                              if actor.can("policies.overtime.view") else []),
        "genders": Gender.choices, "marital_statuses": MaritalStatus.choices,
        "military_statuses": MilitaryStatus.choices, "wage_types": WageType.choices,
        "frequencies": PayFrequency.choices,
        "week": [(day.value, day.label) for day in WEEK],
    }


@permission_required(MANAGE)
def employee_new(request):
    if not request.actor.can(SALARY_MANAGE):
        raise Http404  # a new employee starts with their pay
    return render(request, "employees/employee_form.html", {
        **_choices(request), "employee": None, "next_code": selectors.next_code(),
        "new_pay": Compensation(),  # the form starts from the model's defaults
        "today": timezone.localdate(), "endpoint": reverse("employee-list"), "method": "POST",
    })


@permission_required(MANAGE)
def employee_edit(request, pk):
    try:
        employee = selectors.get_employee(pk, request.actor, MANAGE)
    except AppError:
        raise Http404 from None
    return render(request, "employees/employee_form.html", {
        **_choices(request), "employee": employee,
        "endpoint": reverse("employee-detail", args=[employee.pk]), "method": "PUT",
    })


@permission_required(VIEW)
def employee(request, pk):
    try:
        person = selectors.get_employee(pk, request.actor, VIEW)
    except AppError:
        raise Http404 from None
    actor, today = request.actor, timezone.localdate()
    schedules = list(person.schedules.select_related("lateness_policy", "overtime_policy")
                     .order_by("-effective_from", "-id"))
    context = {
        **_choices(request), "employee": person, "today": today,
        "can_manage": actor.can(MANAGE, branch=person.branch_id),
        "can_app_login": actor.can("mobile.signin") and actor.can("admin.users.manage")
        and actor.can(MANAGE, branch=person.branch_id),
        # Linked to a user who also works in the office (not a login made for the app only).
        "linked_user": person.member if person.member_id and not is_app_login(
            person.member.roles.values_list("role__code", flat=True)) else None,
        "can_see_pay": actor.can(SALARY_READ, branch=person.branch_id),
        "can_change_pay": actor.can(SALARY_MANAGE, branch=person.branch_id),
        "can_see_attendance": actor.can("attendance.day.view", branch=person.branch_id),
        "schedules": schedules,
        "schedule": in_effect(person.schedules.all(), today),
        "endpoint": reverse("employee-detail", args=[person.pk]),
    }
    if context["can_see_pay"]:
        history = list(person.pay_history.order_by("-effective_from", "-id"))
        for row in history:
            row.daily, row.hourly = row.terms.daily, row.terms.hourly
        current = next((row for row in history if row.effective_from <= today), None)
        context.update(pay_history=history, pay=current)
    return render(request, "employees/employee.html", context)


# --- Excel import --------------------------------------------------------------------------


@permission_required("employees.employee.import")
def employee_import(request):
    return import_page(request, imports.EmployeeImport(actor=request.actor), ImportPage(
        title=_("Import employees from Excel"),
        intro=_("One employee per row, with their pay and working hours."),
        back_url=reverse("employees"), back_label=_("Employees"),
        template_url=reverse("employee-import-template"), done_url=reverse("employees"),
        done_message=_("%(count)s employees imported.")))


@permission_required("employees.employee.import")
def employee_import_template(request):
    return template_download(imports.EmployeeImport(), "employees.xlsx")


@permission_required(MANAGE)
def hours_group(request):
    return render(request, "employees/hours_group.html", group_page(
        request, MANAGE, title=_("Working hours for a group"),
        intro=_("New working hours for several employees from a date, for good or until a last "
                "day. Each keeps their days off and policies unless you change the days off "
                "too. Preview, then save."),
        back_url=reverse("employees"), back_label=_("Employees"),
        endpoint=reverse("group-hours-list"), done_url=reverse("employees"),
        done_message=_("New hours saved for {count} employees."), detail_label=_("Hours"),
        weekdays=[(day.value, day.label) for day in WEEK]))
