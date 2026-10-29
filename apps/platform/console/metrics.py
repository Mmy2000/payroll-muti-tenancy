"""Usage figures per client, read inside each tenant's own context (RLS stays on: the console
never sees two tenants in one transaction), and rolled up for the platform overview.

A client's activity is what its people save (the audit trail) and the punches that come in
from devices and the app; payroll is the runs approved in the last 30 days."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Max, Sum
from django.db.models.functions import TruncDate
from django.utils import formats, timezone

from apps.core.charts import Point, columns
from apps.core.tenancy import tenant_context
from apps.platform.tenants import limits
from apps.platform.tenants.models import Tenant, TenantStatus

ZERO = Decimal(0)
DAYS = 14


@dataclass
class TenantUsage:
    tenant: Tenant
    display_name: str = ""
    currency: str = ""
    locale: str = ""
    users: int = 0  # active office users (apps.platform.tenants.limits)
    app_logins: int = 0  # active app logins, a limit of their own
    branches: int = 0
    employees: int = 0  # working today
    changes_30d: int = 0
    punches_30d: int = 0
    payslips_30d: int = 0  # in runs approved in the last 30 days
    net_30d: Decimal = ZERO
    last_activity: datetime | None = None
    daily: dict[date, int] = field(default_factory=dict)  # changes per day, last DAYS days

    @property
    def idle_days(self) -> int | None:
        if self.last_activity is None:
            return None
        return (timezone.now() - self.last_activity).days

    @property
    def health(self) -> str:
        """active: used this week; quiet: not this week; idle: a month or more; new: never."""
        days = self.idle_days
        if days is None:
            return "new"
        if days <= 7:
            return "active"
        return "quiet" if days < 30 else "idle"


def tenant_usage(tenant: Tenant) -> TenantUsage:
    from apps.attendance.models import Punch
    from apps.audit.models import AuditEvent
    from apps.employees.models import Employee
    from apps.org.models import Branch, TenantProfile
    from apps.payroll.models import FINAL, PayrollRun, Payslip

    usage = TenantUsage(tenant=tenant)
    now = timezone.now()
    since = now - timedelta(days=30)
    first_day = timezone.localdate() - timedelta(days=DAYS - 1)
    with tenant_context(tenant.id):
        profile = TenantProfile.objects.first()
        if profile is not None:
            usage.display_name = profile.display_name
            usage.currency = profile.functional_currency
            usage.locale = profile.locale
        usage.users = limits.office_users()
        usage.app_logins = limits.app_logins()
        usage.branches = Branch.objects.filter(is_active=True).count()
        today = timezone.localdate()
        usage.employees = Employee.objects.filter(hired_on__lte=today).exclude(
            left_on__lt=today).count()
        changes = AuditEvent.objects.all()
        usage.changes_30d = changes.filter(at__gte=since).count()
        usage.daily = dict(
            changes.filter(at__date__gte=first_day).annotate(day=TruncDate("at"))
            .values("day").annotate(n=Count("id")).values_list("day", "n"))
        punches = Punch.objects.all()
        usage.punches_30d = punches.filter(at__gte=since).count()
        usage.last_activity = max(
            (at for at in (changes.aggregate(last=Max("at"))["last"],
                           punches.filter(at__lte=now).aggregate(last=Max("at"))["last"])
             if at is not None), default=None)
        runs = PayrollRun.objects.filter(status__in=FINAL, approved_at__gte=since)
        usage.payslips_30d = Payslip.objects.filter(run__in=runs).count()
        usage.net_30d = runs.aggregate(net=Sum("net"))["net"] or ZERO
    return usage


@dataclass
class PlatformOverview:
    tenants: list[TenantUsage]
    by_status: dict[str, int]
    new_30d: int
    users: int
    app_logins: int
    employees: int
    payslips_30d: int
    net_by_currency: dict[str, Decimal]
    daily: dict  # a column chart (apps.core.charts.columns): changes saved per day
    health: dict[str, int]


def overview() -> PlatformOverview:
    tenants = list(Tenant.objects.select_related("plan").order_by("slug"))
    live = [t for t in tenants if t.status in (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)]
    usages = [tenant_usage(t) for t in live]
    by_status: dict[str, int] = defaultdict(int)
    for tenant in tenants:
        by_status[tenant.status] += 1
    net_by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for usage in usages:
        if usage.net_30d:
            net_by_currency[usage.currency] += usage.net_30d
    today = timezone.localdate()
    per_day = {today - timedelta(days=n): 0 for n in range(DAYS)}
    for usage in usages:
        for day, count in usage.daily.items():
            if day in per_day:
                per_day[day] += count
    daily = columns([Point(formats.date_format(day, "j/n"), count,
                           title=formats.date_format(day, "l j F"))
                     for day, count in sorted(per_day.items())], whole=True)
    health: dict[str, int] = defaultdict(int)
    for usage in usages:
        health[usage.health] += 1
    month_ago = timezone.now() - timedelta(days=30)
    return PlatformOverview(
        tenants=usages, by_status=dict(by_status),
        new_30d=sum(1 for t in tenants if t.created_at >= month_ago),
        users=sum(u.users for u in usages), app_logins=sum(u.app_logins for u in usages),
        employees=sum(u.employees for u in usages),
        payslips_30d=sum(u.payslips_30d for u in usages),
        net_by_currency=dict(net_by_currency), daily=daily, health=dict(health))
