"""The permissions in the order people work: the sidebar's sections and screens, and within a screen
its steps from seeing to approving. The role page reads this, and a test keeps it in line with
the sidebar (config/context_processors.py). The mobile app has no screen in the sidebar, so it
comes before the settings."""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Screen:
    title: object
    codes: tuple[str, ...]


@dataclass(frozen=True)
class Section:
    title: object
    screens: tuple[Screen, ...]


FLOW = (
    Section(_("People"), (
        Screen(_("Employees"), ("employees.employee.view", "employees.employee.manage",
                                "employees.employee.import")),
        Screen(_("Employees' pay"), ("employees.salary.read", "employees.salary.manage")),
        Screen(_("Departments"), ("org.department.view", "org.department.manage")),
        Screen(_("Positions"), ("org.position.view", "org.position.manage")),
        Screen(_("Evaluations"), ("evaluations.evaluation.view", "evaluations.evaluation.manage")),
    )),
    Section(_("Attendance"), (
        Screen(_("Daily attendance"), ("attendance.day.view", "attendance.day.manage",
                                       "attendance.import")),
        Screen(_("Leave"), ("attendance.leave.view", "attendance.leave.request",
                            "attendance.leave.approve", "attendance.leave_type.manage")),
        Screen(_("Hourly leave"), ("attendance.hourly.view", "attendance.hourly.request",
                                   "attendance.hourly.approve")),
        Screen(_("Fingerprint devices"), ("devices.device.view", "devices.device.manage")),
    )),
    Section(_("Pay"), (
        Screen(_("Pay items given"), ("compensation.entry.view", "compensation.entry.manage")),
        Screen(_("Incentives"), ("adjustments.incentive.view", "adjustments.incentive.manage",
                                 "adjustments.incentive.approve")),
        Screen(_("Penalties"), ("adjustments.penalty.view", "adjustments.penalty.manage",
                                "adjustments.penalty.approve")),
        Screen(_("Salary advances"), ("loans.advance.view", "loans.advance.manage")),
        Screen(_("Loans"), ("loans.loan.view", "loans.loan.manage")),
    )),
    Section(_("Payroll"), (
        Screen(_("Payroll runs"), ("payroll.run.read", "payroll.run.calculate",
                                   "payroll.run.approve", "payroll.run.pay",
                                   "payroll.run.reverse")),
        Screen(_("Reports"), ("reports.export",)),
    )),
    Section(_("Pay setup"), (
        Screen(_("Pay calendars"), ("payroll.calendar.manage",)),
        Screen(_("Pay items"), ("compensation.item.view", "compensation.item.manage")),
        Screen(_("Lateness"), ("policies.lateness.view", "policies.lateness.manage")),
        Screen(_("Overtime"), ("policies.overtime.view", "policies.overtime.manage")),
        Screen(_("Income tax"), ("policies.tax.view", "policies.tax.manage")),
        Screen(_("Social insurance"), ("policies.insurance.view", "policies.insurance.manage")),
        Screen(_("Public holidays"), ("policies.holiday.view", "policies.holiday.manage")),
    )),
    Section(_("Mobile app"), (
        Screen(_("Mobile app"), ("mobile.signin", "mobile.qr.manage", "mobile.monitor.track")),
    )),
    Section(_("Settings"), (
        Screen(_("Company"), ("org.settings.manage",)),
        Screen(_("Branches"), ("org.branch.view", "org.branch.manage")),
        Screen(_("Users"), ("admin.users.view", "admin.users.manage")),
        Screen(_("Roles"), ("admin.roles.manage",)),
        Screen(_("WhatsApp"), ("messaging.whatsapp.link",)),
        Screen(_("Sent messages"), ("messaging.view", "messaging.send")),
        Screen(_("Activity"), ("admin.audit.history",)),
        Screen(_("Sign-ins"), ("admin.signins.history",)),
    )),
)
