# ADR-105: One structure for every app

**Status:** Accepted · 2026-10-31

## Context

The apps had grown three layouts. `views.py` meant pages in some apps and the mobile API in
another; routes lived in `views.py`, `api.py`, `urls.py` or `web_api.py`. Of the 202 functions in
service files only 112 wrote anything: the rest were reads, checks and helpers, because only three
apps had a `selectors.py`. Web views held about 166 queries. `core` imported business apps, and
most imports between apps formed cycles through `platform`.

The standards could not prevent this: they were copied from Gweb, named its apps, accepted two
layouts and had broken links.

## Decision

- Every app has the same shape ([architecture standards](../standards/architecture.md)): `api/`
  for JSON, `web/` for pages, `services` for writes, `selectors.py` for reads, `validators.py` for
  checks against data, `domain/` for pure calculations. An optional file exists only when the app
  has something to put in it.
- Dependencies between apps go one way, down a fixed list of layers. What `core` needed from
  `org` and `platform.tenants` moved up into them, and `config/` holds the page shell.
- Setting up a client needs every app, so provisioning and the demo data live in the console,
  the top layer. Plan limits live beside what they count (`org.limits`, `iam.limits`).
- `tests/test_architecture.py` checks all of it, so it can't drift again.
- The move changes no behaviour: routes, API schema, permissions and database schema stay
  identical, compared against a snapshot taken before the work began.

## Alternatives

- **Repositories over the ORM.** Refused. `TenantScopedModel` already gives a fail-closed,
  tenant-scoped manager, and selectors are the one place reads live. A repository would wrap the
  ORM a second time, and hide `select_for_update` and `select_related`, which the services need to
  see. It would make sense with a second storage backend, and there isn't one.
- **Service classes and dependency injection.** Refused. Functions with a frozen input and an
  `actor` are easy to call from jobs, imports and tests; a class would add a constructor and no
  behaviour.
- **Keeping two accepted layouts.** Refused: it is what produced the drift.

## Consequences

- A developer can find any piece of code from the kind of thing it is.
- Some small apps have small files, and `selectors.py` holds one-line functions in places. That
  costs little, and the rule stays free of exceptions.
- Anyone adding code must follow the layout: the test fails otherwise.
