"""Attendance pages. They read and render; every save goes to the JSON API (apps/attendance/api).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from apps.core import months
from apps.core.errors import AppError
from apps.core.import_page import ImportPage, import_page, template_download
from apps.core.listing import Choice, ListQuery
from apps.employees.selectors import get_employee, visible_employees
from apps.employees.targets import employed_on
from apps.employees.web.targets import employee_choices, group_page
from apps.iam.authz import permission_required
from apps.org.models import Branch
from apps.org.selectors import visible_departments

from .. import entries, hourly, leave, selectors
from ..domain.summary import summarize
from ..imports import PunchImport
from ..models import DayKind, HourlyLeave, LeaveRequest, LeaveType, RequestStatus
from ..selectors import evaluate

VIEW = "attendance.day.view"


def _date(text: str, default: date) -> date:
    try:
        return date.fromisoformat(text) if text else default
    except ValueError:
        return default


def _branches(actor, code: str):
    allowed = actor.branch_ids(code)
    branches = Branch.objects.filter(is_active=True).order_by("code")
    return branches if allowed is None else branches.filter(pk__in=allowed)


# --- the daily sheet -----------------------------------------------------------------------


@permission_required(VIEW)
def daily(request):
    """Everyone's day: what the clock or a manager says, and a way to correct it."""
    actor, today = request.actor, timezone.localdate()
    day = _date(request.GET.get("date", ""), today)
    branches = list(_branches(actor, VIEW))
    branch = next((b for b in branches if str(b.pk) == request.GET.get("branch")), None)
    departments = list(visible_departments(actor, VIEW).filter(is_active=True))
    department = next((d for d in departments if str(d.pk) == request.GET.get("department")),
                      None)

    people = visible_employees(actor, VIEW).filter(employed_on(day)).select_related(
        "branch", "department").order_by("code")
    if branch:
        people = people.filter(branch=branch)
    if department:
        people = people.filter(department=department)
    people = list(people)
    results = evaluate(people, day, day, today=today)
    rows = [{"employee": e, "day": results[e.pk][0],
             "can_manage": actor.can(entries.MANAGE, branch=e.branch_id)} for e in people]
    return render(request, "attendance/daily.html", {
        "day": day, "today": today, "rows": rows, "summary": summarize(r["day"] for r in rows),
        "previous": day - timedelta(days=1), "next": day + timedelta(days=1),
        "branches": branches, "branch": branch, "departments": departments,
        "department": department, "kinds": DayKind.choices,
        "can_manage": any(r["can_manage"] for r in rows),
        "can_manage_any": actor.can(entries.MANAGE),
        "can_import": actor.can("attendance.import"),
    })


# --- one employee's month ------------------------------------------------------------------


@permission_required(VIEW)
def employee_month(request, pk):
    actor, today = request.actor, timezone.localdate()
    try:
        employee = get_employee(pk, actor, VIEW)
    except AppError:
        raise Http404 from None
    first = months.parse(request.GET.get("month", ""), today)
    last = months.last_day(first)
    days = evaluate([employee], first, last, today=today)[employee.pk]
    context = {
        "employee": employee, "days": days, "summary": summarize(days), "month": first,
        "previous": (first - timedelta(days=1)).replace(day=1), "next": last + timedelta(days=1),
        "can_manage": actor.can(entries.MANAGE, branch=employee.branch_id),
        "kinds": DayKind.choices,
    }
    if actor.can("attendance.leave.view", branch=employee.branch_id):
        context["balance"] = selectors.balance(employee, first.year)
    return render(request, "attendance/employee_month.html", context)


# --- leave and hourly leave ----------------------------------------------------------------

REQUEST_TABS = [(RequestStatus.PENDING, _lazy("Waiting")),
                (RequestStatus.APPROVED, _lazy("Approved")),
                (RequestStatus.REJECTED, _lazy("Rejected")),
                (RequestStatus.CANCELLED, _lazy("Cancelled")), ("all", _lazy("All"))]


def _by_status(queryset, value):
    return queryset if value == "all" else queryset.filter(status=value)


def _requests_page(request, *, model, view_permission, approve_permission, template, date_field,
                   extra=None):
    found = ListQuery(request, permission=view_permission,
                      search=("employee__name", "reason"), date_field=date_field,
                      branch_field="employee__branch_id",
                      party="employee_id", party_model="employees.Employee",
                      choices=[Choice("status", _("Status"), REQUEST_TABS, apply=_by_status,
                                      value=RequestStatus.PENDING, tabs=True)])
    employees = visible_employees(request.actor, view_permission)
    rows = found.apply(model.objects.filter(employee__in=employees)
                       .select_related("employee", *(extra or ())))
    return render(request, template, {
        "filters": found, "page": found.page(rows.order_by(f"-{date_field}", "-id")),
        "can_approve": request.actor.can(approve_permission),
    })


def _request_form_context(request, permission: str) -> dict:
    return {"employees": employee_choices(request.actor, permission),
            "today": timezone.localdate(),
            "selected": request.GET.get("employee", "")}


@permission_required("attendance.leave.view")
def leave_requests(request):
    return _requests_page(request, model=LeaveRequest, view_permission="attendance.leave.view",
                          approve_permission=leave.APPROVE, template="attendance/leave.html",
                          date_field="start_date", extra=("leave_type",))


@permission_required(leave.REQUEST)
def leave_request_new(request):
    return render(request, "attendance/leave_form.html", {
        **_request_form_context(request, leave.REQUEST),
        "leave_types": LeaveType.objects.filter(is_active=True),
        "can_approve": request.actor.can(leave.APPROVE)})


@permission_required("attendance.hourly.view")
def hourly_leave(request):
    return _requests_page(request, model=HourlyLeave, view_permission="attendance.hourly.view",
                          approve_permission=hourly.APPROVE, template="attendance/hourly.html",
                          date_field="work_date")


@permission_required(hourly.REQUEST)
def hourly_leave_new(request):
    return render(request, "attendance/hourly_form.html", {
        **_request_form_context(request, hourly.REQUEST),
        "can_approve": request.actor.can(hourly.APPROVE)})


@permission_required(hourly.REQUEST)
def hourly_leave_group(request):
    return render(request, "attendance/hourly_group.html", group_page(
        request, hourly.REQUEST, title=_("Hourly leave for a group"),
        intro=_("The same hours away for several employees, one or more spans in the day. "
                "Each is checked on their own: overlaps, their schedule and their monthly "
                "allowance. Preview, then save."),
        back_url=reverse("hourly-leave"), back_label=_("Hourly leave"),
        endpoint=reverse("hourly-leave-group"), done_url=reverse("hourly-leave") + "?status=all",
        done_message=_("{count} hourly leaves saved."), detail_label=_("Hours"),
        can_approve=request.actor.can(hourly.APPROVE)))


@permission_required(entries.MANAGE)
def times_group(request):
    return render(request, "attendance/times_group.html", group_page(
        request, entries.MANAGE, title=_("Attendance by hand for a group"),
        intro=_("The times several employees came and left, when the clock didn't record "
                "them. Lateness, early leave and overtime follow from these times as from the "
                "clock's. Preview, then save."),
        back_url=reverse("attendance"), back_label=_("Attendance"),
        endpoint=reverse("attendance-day-times"), done_url=reverse("attendance"),
        done_message=_("{count} days saved."), detail_label=_("Came – left")))


@permission_required("attendance.leave.view")
def leave_types(request):
    return render(request, "attendance/leave_types.html", {
        "leave_types": LeaveType.objects.order_by("code"),
        "can_manage": request.actor.can(leave.MANAGE_TYPES)})


# --- Excel import --------------------------------------------------------------------------


@permission_required("attendance.import")
def punch_import(request):
    return import_page(request, PunchImport(actor=request.actor), ImportPage(
        title=_("Import attendance from Excel"),
        intro=_("One row per employee and day: the employee's code, the date, the time they "
                "came and the time they left."),
        back_url=reverse("attendance"), back_label=_("Attendance"),
        template_url=reverse("attendance-import-template"), done_url=reverse("attendance"),
        done_message=_("%(count)s rows imported.")))


@permission_required("attendance.import")
def punch_import_template(request):
    return template_download(PunchImport(), "attendance.xlsx")
