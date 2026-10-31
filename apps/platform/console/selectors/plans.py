"""Plans as the console reads them."""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from apps.platform.tenants.models import Plan, Tenant, TenantStatus


def plans_with_clients() -> QuerySet[Plan]:
    return Plan.objects.annotate(
        clients=Count("tenants", distinct=True),
        live=Count("tenants", filter=Q(tenants__status=TenantStatus.ACTIVE), distinct=True))


def plan_labels() -> list[tuple[str, str]]:
    return [(p.code, p.label) for p in Plan.objects.all()]


def find_plan(pk: int) -> Plan | None:
    return Plan.objects.filter(pk=pk).first()


def find_plan_by_code(code: str) -> Plan | None:
    return Plan.objects.filter(code=code).first()


def clients_on(plan: Plan) -> list[Tenant]:
    return list(plan.tenants.order_by("name"))


def replacement_for(plan: Plan) -> Plan | None:
    """The plan offered for a deleted plan's clients; None when this is the last plan."""
    others = Plan.objects.exclude(pk=plan.pk)
    if not others.exists():
        return None
    return others.filter(is_default=True).first() or others.first()
