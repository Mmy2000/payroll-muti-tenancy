"""Plans, and which features each plan and client has."""

from __future__ import annotations

from django.db import transaction

from apps.platform.tenants import features as feature_registry
from apps.platform.tenants.models import Plan, PlanFeature, Tenant
from apps.platform.tenants.services import record


def _along_with(others) -> dict:
    return {"also": ", ".join(f.key for f in others)} if others else {}


def set_plan_feature(plan: Plan, *, key: str, enabled: bool, actor) -> tuple:
    """Returns the other features changed with it."""
    with transaction.atomic():
        others = feature_registry.set_for_plan(plan, key, enabled)
    record(actor, "feature.plan", None, plan=plan.code, feature=key, enabled=enabled,
           **_along_with(others))
    return others


def set_client_feature(tenant: Tenant, *, key: str, state: str, actor) -> tuple:
    """`state` is on, off or default (back to its plan). Returns the other features changed."""
    with transaction.atomic():
        others = feature_registry.set_for_client(tenant, key,
                                                 None if state == "default" else state == "on")
    record(actor, "feature.client", tenant, feature=key, state=state, **_along_with(others))
    return others


def save_plan(plan: Plan, *, features: dict[str, bool], changes: dict, created: bool,
              actor) -> Plan:
    """Save a plan and its choice for each feature. `changes` is what the event lists."""
    with transaction.atomic():
        plan.save()
        for key, enabled in features.items():
            PlanFeature.objects.update_or_create(plan=plan, key=key,
                                                 defaults={"enabled": enabled})
    feature_registry.forget()
    record(actor, "plan.created" if created else "plan.updated", None, plan=plan.code, **changes)
    return plan


def delete_plan(plan: Plan, *, clients: list[Tenant], move_to: str, actor) -> None:
    """Delete a plan. Its clients (if any) move to another plan first, in the same step."""
    target = Plan.objects.get(code=move_to)
    with transaction.atomic():
        for tenant in clients:
            tenant.plan = target
            tenant.save(update_fields=["plan", "updated_at"])
            record(actor, "tenant.updated", tenant, plan=target.code)
        if plan.is_default:
            target.is_default, target.is_active = True, True
            target.save()
        code = plan.code
        plan.delete()
    feature_registry.forget()
    record(actor, "plan.deleted", None, plan=code, moved_to=target.code, clients=len(clients))
