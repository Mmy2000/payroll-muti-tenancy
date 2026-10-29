"""The employee list (PayRole GHA12/GHA20, دليل الموظفين): their card, and their pay for
readers allowed to see pay (`employees.salary.read`)."""

from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.history import in_effect
from apps.employees.services import SALARY_READ, VIEW

from ..registry import WHO_FILTERS, Column, Filter, Report, Table, register

SHOW = (("working", _("Working")), ("left", _("Left")), ("all", _("All")))


@register
class EmployeeList(Report):
    code, section, permission = "employee_list", "people", VIEW
    title = _("Employee list")
    description = _("Every employee's card: job, branch, department, hiring date and contact; "
                    "and their current pay, for those who may see pay.")
    filters = (*WHO_FILTERS, Filter("show", "choice", _("Show"), SHOW, "working"))

    def run(self, params, scope):
        today = timezone.localdate()
        people = scope.employees()
        show = params.get("show")
        if show == "working":
            people = people.exclude(left_on__lt=today)
        elif show == "left":
            people = people.filter(left_on__lt=today)
        pay = scope.can(SALARY_READ)
        columns = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("job", _("Job")), Column("branch", _("Branch")),
                   Column("department", _("Department")), Column("hired", _("Hired on"), "date"),
                   Column("left", _("Left on"), "date"), Column("phone", _("Phone"), "code"),
                   Column("insurance", _("Insurance number"), "code")]
        if pay:
            columns += [Column("wage_type", _("Pay counted as")), Column("paid", _("Paid")),
                        Column("salary", _("Salary or wage"), "money")]
        rows = []
        for person in people:
            row = {"code": person.code, "name": person.name, "job": person.job_title,
                   "branch": person.branch.name,
                   "department": person.department.name if person.department else "",
                   "hired": person.hired_on, "left": person.left_on, "phone": person.phone,
                   "insurance": person.insurance_number,
                   "_urls": {"name": reverse("employee", args=[person.pk])}}
            current = in_effect(person.pay_history.all(), min(today, person.left_on or today))
            if pay and current is not None:
                row.update(wage_type=current.get_wage_type_display(),
                           paid=current.get_pay_frequency_display(), salary=current.salary)
            rows.append(row)
        table = Table(self.title, columns, rows)
        table.note = _("%(count)s employees.") % {"count": len(rows)}
        return [table]
