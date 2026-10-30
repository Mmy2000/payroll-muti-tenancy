"""Features: modules switched on or off per client by the platform admin.

A feature owns a set of permissions (by prefix). When it is off for a client, those permissions
are treated as not granted for everyone in that workspace, Owners included (`Actor.can`), so
the sidebar, buttons, dashboard blocks, pages and API endpoints that ask for them all disappear
or refuse at once, with no per-screen code. Payroll calculators and background jobs ask
`is_enabled()` for the feature they belong to.

Whether a feature is on for a client:
    1. the client's own setting (platform → client → Features), if there is one;
    2. else its plan's choice (platform → Plans), if one was saved;
    3. else the feature's own default.
It is then *effectively* on only if every feature it `requires` is effectively on too: switching
off attendance also switches off overtime, lateness, devices and the mobile app.

The console keeps the choices themselves consistent (`set_for_client`, `set_for_plan`): switching a
feature on also switches on what it needs, and switching it off also switches off what depends
on it, so "on, but it cannot work" is not a state anyone can save. `effective` still guards the
rest (a client moved to a plan without a feature it relies on).

Only the platform admin changes features; a client's own users, Owners included, cannot.

Adding a module: in its `permissions.py`, register its permission codes and its feature with
`register_feature(Feature(...))`, listing the permission prefixes it owns and what it requires.
It then shows up for the platform admin on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

# A feature with no saved choice falls back on its default, so adding a module changes nothing
# for existing clients until it is switched for a plan or a client.
CACHE_SECONDS = 300

# Groups the platform admin sees the features in.
ATTENDANCE, PAY, PEOPLE, TOOLS = _("Attendance"), _("Pay"), _("People"), _("Tools")


@dataclass(frozen=True)
class Feature:
    key: str
    label: object
    description: object
    group: object
    icon: str
    permissions: tuple[str, ...]  # permission code prefixes this feature owns
    default: bool = True  # with no choice saved for the plan or the client
    requires: tuple[str, ...] = ()  # keys of features that must be on for this one to work

    def owns(self, code: str) -> bool:
        return any(code == p or code.startswith(p) for p in self.permissions)


FEATURES: list[Feature] = []
BY_KEY: dict[str, Feature] = {}


def register_feature(feature: Feature) -> None:
    if feature.key in BY_KEY:
        raise ValueError(f"Feature {feature.key} registered twice")
    FEATURES.append(feature)
    BY_KEY[feature.key] = feature


def _cache_key(tenant_id: int) -> str:
    return f"features:{tenant_id}"


def forget(tenant_id: int | None = None) -> None:
    """Drop cached states: one client's, or every client's (a plan default changed)."""
    if tenant_id is not None:
        cache.delete(_cache_key(tenant_id))
        return
    from .models import Tenant

    cache.delete_many([_cache_key(pk) for pk in Tenant.objects.values_list("pk", flat=True)])


def plan_defaults() -> dict[str, dict[str, bool]]:
    """{plan: {feature key: on?}} with the platform's saved choices over the code defaults."""
    from .models import Plan, PlanFeature

    table = {code: {f.key: f.default for f in FEATURES}
             for code in Plan.objects.values_list("code", flat=True)}
    for row in PlanFeature.objects.filter(key__in=BY_KEY):
        table.setdefault(row.plan_id, {})[row.key] = row.enabled
    return table


def effective(chosen: dict[str, bool]) -> dict[str, bool]:
    """Apply `requires`: a feature is on only if it is chosen and everything it needs is on.
    Unknown required keys count as off."""
    result: dict[str, bool] = {}

    def resolve(key: str, path: tuple[str, ...]) -> bool:
        if key in result:
            return result[key]
        feature = BY_KEY.get(key)
        if feature is None or key in path:  # unknown, or a cycle: refuse rather than loop
            return False
        on = chosen.get(key, feature.default) and all(
            resolve(dep, (*path, key)) for dep in feature.requires)
        result[key] = on
        return on

    for feature in FEATURES:
        resolve(feature.key, ())
    return result


@dataclass(frozen=True)
class FeatureState:
    feature: Feature
    chosen: bool  # what the client's or plan's setting says
    enabled: bool  # chosen, and everything it requires is on
    plan_default: bool
    custom: bool  # the client's own setting overrides the plan
    blocked_by: tuple[Feature, ...]  # required features that are off, when chosen but not on
    needs: tuple[Feature, ...] = ()  # what it relies on, directly or not
    stops: tuple[Feature, ...] = ()  # what is on and would go off with it

    @property
    def stops_text(self) -> str:
        return labels(self.stops)


def needs(key: str) -> tuple[Feature, ...]:
    """What a feature relies on, directly or through another, in the registry's order."""
    found: set[str] = set()

    def walk(name: str) -> None:
        for required in BY_KEY[name].requires if name in BY_KEY else ():
            if required in BY_KEY and required not in found:
                found.add(required)
                walk(required)

    walk(key)
    return tuple(f for f in FEATURES if f.key in found)


def needed_by(key: str) -> tuple[Feature, ...]:
    """The features that rely on this one, directly or not."""
    return tuple(f for f in FEATURES if BY_KEY[key] in needs(f.key))


def labels(items) -> str:
    return ", ".join(str(f.label) for f in items)


def knock_on(chosen: dict[str, bool], key: str, on: bool) -> tuple[Feature, ...]:
    """The other features that have to change for `key` to go on (what it needs) or off (what
    depends on it)."""
    others = needs(key) if on else needed_by(key)
    return tuple(f for f in others if chosen.get(f.key, f.default) != on)


def set_for_client(tenant, key: str, on: bool | None) -> tuple[Feature, ...]:
    """Set a feature for one client (None: back to its plan), with what that brings along.
    Returns the other features changed."""
    from .models import TenantFeature

    current = {s.feature.key: s for s in states(tenant)}
    value = current[key].plan_default if on is None else on
    others = knock_on({k: s.chosen for k, s in current.items()}, key, value)
    if on is None:
        TenantFeature.objects.filter(tenant=tenant, key=key).delete()
    else:
        TenantFeature.objects.update_or_create(tenant=tenant, key=key, defaults={"enabled": on})
    for feature in others:
        TenantFeature.objects.update_or_create(tenant=tenant, key=feature.key,
                                               defaults={"enabled": value})
    forget(tenant.pk)
    return others


def set_for_plan(plan, key: str, on: bool) -> tuple[Feature, ...]:
    """Set a feature for a plan, with what that brings along. Returns the others changed."""
    from .models import PlanFeature

    others = knock_on(plan_defaults().get(plan.code, {}), key, on)
    for name in (key, *(f.key for f in others)):
        PlanFeature.objects.update_or_create(plan=plan, key=name, defaults={"enabled": on})
    forget()
    return others


def states(tenant) -> list[FeatureState]:
    from .models import TenantFeature

    defaults = plan_defaults().get(tenant.plan_id, {})
    own = dict(TenantFeature.objects.filter(tenant=tenant).values_list("key", "enabled"))
    chosen = {f.key: own.get(f.key, defaults.get(f.key, f.default)) for f in FEATURES}
    on = effective(chosen)
    return [
        FeatureState(
            feature=f, chosen=chosen[f.key], enabled=on[f.key],
            plan_default=defaults.get(f.key, f.default), custom=f.key in own,
            blocked_by=tuple(BY_KEY[d] for d in f.requires if d in BY_KEY and not on[d])
            if chosen[f.key] and not on[f.key] else (),
            needs=needs(f.key), stops=knock_on(chosen, f.key, False) if chosen[f.key] else (),
        )
        for f in FEATURES
    ]


def enabled_keys(tenant_id: int) -> frozenset[str]:
    keys = cache.get(_cache_key(tenant_id))
    if keys is None:
        from .models import Tenant

        tenant = Tenant.objects.filter(pk=tenant_id).first()
        keys = frozenset(s.feature.key for s in states(tenant) if s.enabled) if tenant else \
            frozenset()
        cache.set(_cache_key(tenant_id), keys, CACHE_SECONDS)
    return keys


def is_enabled(tenant_id: int, key: str) -> bool:
    return key in enabled_keys(tenant_id)


def disabled_feature_for(code: str, tenant_id: int | None) -> Feature | None:
    """The switched-off feature that owns permission `code` for this client, if any."""
    if tenant_id is None:
        return None
    enabled = enabled_keys(tenant_id)
    for feature in FEATURES:
        if feature.key not in enabled and feature.owns(code):
            return feature
    return None


def disabled_permissions(tenant_id: int | None) -> frozenset[str]:
    """Every registered permission code owned by a feature that is off for this client."""
    if tenant_id is None:
        return frozenset()
    from apps.iam.catalog import permissions

    off = [f for f in FEATURES if f.key not in enabled_keys(tenant_id)]
    return frozenset(code for code in permissions() if any(f.owns(code) for f in off))
