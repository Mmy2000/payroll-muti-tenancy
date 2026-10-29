# ADR-104: The browser's API at `/api/web/`; `/api/v1/` keeps PayRole's mobile contract

**Status:** Accepted · 2026-10-28

## Context

The existing mobile app talks to PayRole at `/api/v1/` (JWT sign-in, punches, leave,
notifications, tracking), and must keep working unchanged. Gweb serves its browser API at
`/api/v1/`, with session authentication and a different error envelope.

## Decision

- The browser's JSON API (AJAX from `static/core/js/api.js`) lives at `/api/web/`.
- `/api/v1/` is reserved for the mobile app (phase 6), with PayRole's paths, payloads and JWT.
- Each client's app points at the client's own host, so the tenant comes from the host for the
  mobile API too. A token carries its tenant and is refused on another tenant's host.

## Consequences

- The two APIs can evolve separately: the web API follows this project's conventions, the mobile
  API follows PayRole's contract.
