# Architecture decision records

An ADR records a decision that is hard to reverse or that everyone must follow: the problem,
what was decided, what else was considered, and the consequences.

## Inherited from Gweb

The foundation (tenancy, identity, permissions, jobs, audit) comes from Gweb (`Saas_ERP`), and
its code cites Gweb's decisions. The ones that apply here:

| ADR | Decision |
|---|---|
| ADR-001 | One Django project and one PostgreSQL database for every client |
| ADR-002 | Tenant isolation by row-level security on `tenant_id`, plus a fail-closed ORM |
| ADR-004 | A global `User` with no username; a per-tenant `Membership` carries the username |
| ADR-008 | Documents: drafts are edited; posting numbers them; posted ones are only cancelled |
| [ADR-019](ADR-019-lint-without-formatter.md) | Enforce lint, not an auto-formatter |
| [ADR-020](ADR-020-quality-gates.md) | Quality gates: one local command, the same in CI |
| [ADR-021](ADR-021-platform-tasks-outside-a-transaction.md) | Platform tasks may run outside a transaction |
| [ADR-022](ADR-022-identity-across-workspaces.md) | Who may change a user who belongs to several workspaces |

## Payroll's own

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-101](ADR-101-django-6.md) | Django 6, not the 5.2 LTS Gweb uses | Accepted | 2026-10-28 |
| [ADR-102](ADR-102-features-registered-by-apps.md) | Features registered by each app, with dependencies | Accepted | 2026-10-28 |
| [ADR-103](ADR-103-seeding-registry.md) | A seeding registry for new clients | Accepted | 2026-10-28 |
| [ADR-104](ADR-104-web-api-and-mobile-api.md) | The browser's API at `/api/web/`; `/api/v1/` keeps PayRole's mobile contract | Accepted | 2026-10-28 |
| [ADR-105](ADR-105-one-app-structure.md) | One structure for every app | Accepted | 2026-10-31 |
| [ADR-106](ADR-106-assignments-and-scope.md) | Dated assignments, company-wide permissions, leaving ends access | Accepted | 2026-11-01 |

## When to write one

- A change to tenancy, permissions, identity or payroll calculation rules.
- A new dependency, process or external service.
- A new pattern or registry.
