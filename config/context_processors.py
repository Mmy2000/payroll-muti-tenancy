"""Template context for the application shell: navigation (filtered by permission) and the
tenant profile. Only computed on tenant hosts for signed-in members."""

from __future__ import annotations

from dataclasses import dataclass

from django.urls import reverse
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    icon: str
    permission: str  # or a function of the actor (a page open to several permissions)
    also_active_for: tuple[str, ...] = ()

    def allows(self, actor) -> bool:
        return self.permission(actor) if callable(self.permission) else \
            actor.can(self.permission)


def _any_report(actor) -> bool:
    from apps.reports.web.views import visible_reports

    return bool(visible_reports(actor))


@dataclass(frozen=True)
class NavSection:
    """A group of the sidebar: a header that opens and closes (remembered per user)."""

    key: str
    title: str
    icon: str
    items: list[NavItem]


NAV_COOKIE = "payroll_nav"  # the groups the user left open, comma separated
FLAT = {"overview"}  # shown as plain links, without a header

# Each phase adds its own section (employees, attendance, payroll…). An item shows only when the
# member has its permission, so a feature switched off for the client hides its links too.
NAVIGATION: list[NavSection] = [
    NavSection("overview", _("Overview"), "layout-dashboard", [
        NavItem(_("Dashboard"), "home", "layout-dashboard", "authenticated"),
    ]),
    NavSection("people", _("People"), "users", [
        NavItem(_("Employees"), "employees", "users", "employees.employee.view",
                ("employee-new", "employee", "employee-edit", "employee-import",
                 "employees-hours")),
        NavItem(_("Departments"), "departments", "users-round", "org.department.view",
                ("department-new", "department-edit")),
        NavItem(_("Positions"), "positions", "briefcase", "org.position.view",
                ("position-new", "position-edit")),
        NavItem(_("Evaluations"), "evaluations", "clipboard-check", "evaluations.evaluation.view",
                ("evaluation-new", "evaluation")),
    ]),
    NavSection("attendance", _("Attendance"), "clock", [
        NavItem(_("Daily attendance"), "attendance", "clock", "attendance.day.view",
                ("attendance-employee", "attendance-import", "attendance-times")),
        NavItem(_("Leave"), "leave-requests", "calendar-days", "attendance.leave.view",
                ("leave-request-new", "leave-types")),
        NavItem(_("Hourly leave"), "hourly-leave", "calendar-clock", "attendance.hourly.view",
                ("hourly-leave-new", "hourly-leave-for-group")),
        NavItem(_("Fingerprint devices"), "devices", "fingerprint", "devices.device.view",
                ("device",)),
    ]),
    NavSection("pay", _("Pay"), "hand-coins", [
        NavItem(_("Pay items given"), "pay-item-assignments", "hand-coins",
                "compensation.entry.view", ("pay-item-assignment-new",)),
        NavItem(_("Incentives"), "incentives", "award", "adjustments.incentive.view",
                ("incentive-new", "incentive-types", "incentive-batch")),
        NavItem(_("Penalties"), "penalties", "gavel", "adjustments.penalty.view",
                ("penalty-new", "penalty-types", "penalty-batch")),
        NavItem(_("Salary advances"), "advances", "wallet", "loans.advance.view"),
        NavItem(_("Loans"), "loans", "piggy-bank", "loans.loan.view", ("loan-new", "loan")),
    ]),
    NavSection("payroll", _("Payroll"), "calculator", [
        NavItem(_("Payroll runs"), "payroll-runs", "calculator", "payroll.run.read",
                ("payroll-run-new", "payroll-run", "payslip")),
        NavItem(_("Reports"), "reports", "chart-column", _any_report, ("report",)),
    ]),
    NavSection("pay-setup", _("Pay setup"), "wallet", [
        NavItem(_("Pay calendars"), "pay-calendars", "calendar", "payroll.calendar.manage"),
        NavItem(_("Pay items"), "pay-items", "hand-coins", "compensation.item.view",
                ("pay-item-new", "pay-item-edit")),
        NavItem(_("Lateness"), "lateness-policies", "alarm-clock", "policies.lateness.view",
                ("lateness-policy-new", "lateness-policy-edit")),
        NavItem(_("Overtime"), "overtime-policies", "timer", "policies.overtime.view",
                ("overtime-policy-new", "overtime-policy-edit")),
        NavItem(_("Income tax"), "tax-tables", "landmark", "policies.tax.view",
                ("tax-table-new", "tax-table-edit")),
        NavItem(_("Social insurance"), "insurance-rates", "shield-check",
                "policies.insurance.view", ("insurance-rate-new", "insurance-rate-edit")),
        NavItem(_("Public holidays"), "holidays", "calendar-days", "policies.holiday.view"),
    ]),
    NavSection("settings", _("Settings"), "settings", [
        NavItem(_("Company"), "company", "settings", "org.settings.manage"),
        NavItem(_("Branches"), "branches", "store", "org.branch.view",
                ("branch-new", "branch-edit")),
        NavItem(_("Users"), "users", "users", "admin.users.view", ("user-new", "user-edit")),
        NavItem(_("Roles"), "roles", "shield-check", "admin.users.view", ("role-new", "role-edit")),
        NavItem(_("WhatsApp"), "whatsapp", "send", "messaging.whatsapp.link"),
        NavItem(_("Sent messages"), "sent-messages", "inbox", "messaging.view"),
        NavItem(_("Activity"), "activity", "history", "admin.audit.history"),
        NavItem(_("Sign-ins"), "sign-ins", "log-in", "admin.signins.history"),
    ]),
]


def _navigation(request):
    actor = request.actor
    current = getattr(request.resolver_match, "url_name", None)
    remembered = request.COOKIES.get(NAV_COOKIE)
    opened = set(remembered.split(",")) if remembered else set()
    sections = []
    for section in NAVIGATION:
        visible = [
            {"label": item.label, "url": reverse(item.url_name), "icon": item.icon,
             "active": current == item.url_name or current in item.also_active_for}
            for item in section.items if item.allows(actor)
        ]
        if not visible:
            continue
        holds_current = any(item["active"] for item in visible)
        sections.append({"key": section.key, "title": section.title, "icon": section.icon,
                         # A group of one screen is just a link to it.
                         "items": visible, "flat": section.key in FLAT or len(visible) == 1,
                         "current": holds_current,
                         # The current page's group is always open; others as the user left them.
                         "open": holds_current or section.key in opened})
    return sections


def _bell(request) -> dict:
    from apps.notifications.kinds import ICONS
    from apps.notifications.selectors import ICONS as QUEUE_ICONS
    from apps.notifications.selectors import unread_count

    unread = unread_count(request.actor.membership)
    # Every icon the bell's menu may draw, for its script (notification kinds and queues).
    icons = sorted({*ICONS, *QUEUE_ICONS})
    return {"unread": unread, "label": "99+" if unread > 99 else str(unread), "icons": icons}


def _shortcuts(request) -> dict:
    """The member's pinned screens, and whether the screen they are on can be (or is) pinned."""
    from apps.iam.shortcuts import pinned, screens

    current = getattr(request.resolver_match, "url_name", None)
    mine = pinned(request.actor)
    item = screens().get(current)
    screen = None
    if item is not None and item.allows(request.actor):
        screen = {"name": current, "label": str(item.label),
                  "pinned": any(s["screen"] == current for s in mine)}
    return {"items": mine, "screen": screen}


def shell(request):
    if getattr(request, "actor", None) is None:
        return {}
    from apps.org.models import TenantProfile

    return {
        "ui_strings": {
            "choose_branch_first": gettext("Choose a branch first"),
            "error": gettext("Please correct the highlighted fields."),
            "network": gettext("Could not reach the server. Check your connection and try again."),
            "search": gettext("Type to search…"),
            "no_results": gettext("No matches"),
            "loading": gettext("Searching…"),
            "clear": gettext("Clear"),
            "page_loading": gettext("Loading…"),
            "pinned": gettext("Pinned to your shortcuts."),
            "unpinned": gettext("Removed from your shortcuts."),
        },
        "nav_sections": SimpleLazyObject(lambda: _navigation(request)),
        "shortcuts": SimpleLazyObject(lambda: _shortcuts(request)),
        "bell": SimpleLazyObject(lambda: _bell(request)),
        "tenant_profile": SimpleLazyObject(lambda: TenantProfile.objects.first()),
    }
