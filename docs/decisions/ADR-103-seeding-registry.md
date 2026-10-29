# ADR-103: A seeding registry for new clients

**Status:** Accepted · 2026-10-28

## Context

A new client needs starting data from several apps: system roles, the head office, and later
default insurance rates, tax tables, leave types. Gweb's provisioning imports each business app's
seed function, which makes the platform depend on business apps.

## Decision

`apps.core.seeding`: apps call `register_seed(key, function, after=(...))` from their
`AppConfig.ready()`. Provisioning calls `run_seeds(country=..., currency=..., head_office=...)`
inside the new client's tenant context and language. Seeds run in registration order, each after
the seeds it names in `after`. A seed accepts the keyword arguments it needs and ignores the rest
(`**_`).

## Consequences

- Provisioning (`apps/platform/tenants/services.py`) imports no business app.
- A seed must be safe on an empty client only; it is not a data migration for existing clients.
