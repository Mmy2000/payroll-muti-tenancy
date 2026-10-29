# ADR-102: Features registered by each app, with dependencies

**Status:** Accepted · 2026-10-28

## Context

Every module must be switchable per client by the platform admin (docs/PLAN.md, "Features").
Gweb keeps its features in one list in `apps/platform/tenants/features.py`, and a feature has no
way to say it depends on another. Payroll's modules depend on each other: overtime, lateness and
ZK devices are meaningless without attendance; GPS tracking needs the mobile app.

## Decision

- An app registers its own features in its `permissions.py`, next to its permission codes:
  `register_feature(Feature(key, label, description, group, icon, permissions, default,
  requires))`. Adding a module never edits a central list.
- `requires` names the features that must be on. A feature is *effectively* on only if it is
  chosen (client setting, else plan setting, else its default) and everything it requires is
  effectively on. Unknown requirements and cycles count as off.
- Only the platform admin changes features (Django admin on platform hosts until the console);
  a client's users, Owners included, cannot.
- Code checks a feature in one of two ways:
  - through permissions: a feature that is off removes its permission prefixes from everyone
    (`Actor`), so screens and API endpoints need no code of their own;
  - with `features.is_enabled(tenant_id, key)`, for code that has no permission check: payroll
    calculators, background jobs, device endpoints.

## Consequences

- A feature can only exist once its app does, so the list in the plan arrives phase by phase.
- `tests/test_features.py` checks that each feature owns real permissions, that no permission
  belongs to two features, and that every requirement names a registered feature.
