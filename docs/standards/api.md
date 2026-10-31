# API standards

The JSON API under `/api/web/` on tenant hosts serves the web pages' forms and scripts. This page
describes the contract as implemented (in `apps/core/api/`) and the rules new endpoints follow.
The mobile app has its own API at `/api/v1/`, with PayRole's contract: see
[the mobile API](../mobile-api.md) and ADR-104.

## Versioning and routes

- **Routes:** `config/urls.py` mounts `api/web/` → `config/api_urls.py`, which includes each
  app's `api/urls.py`.
- **Route names:** plural nouns, with actions as sub-paths, e.g.
  `POST /api/web/loans/loans/{id}/cancel/`.
- **Breaking `/api/v1/`** means removing or renaming a field, or changing a type or status code.
  The installed app depends on it, so that needs a new field alongside the old one, and an ADR.
  Adding fields is not breaking.

## Authentication and permissions

- **Session authentication** (the signed-in browser). Unsafe methods need the CSRF token in
  `X-CSRFToken`; `static/core/js/api.js` sends it. The mobile app uses its own Bearer tokens
  (`apps/mobile/api/v1/auth.py`).
- **Every view keeps the default permission class `HasTenantPermission`, and declares
  `required_permissions` for every action:**

  ```python
  required_permissions = {
      "list": "loans.loan.view", "retrieve": "loans.loan.view",
      "create": "loans.loan.manage", "cancel": "loans.loan.manage",
  }
  ```

  - An undeclared action is denied.
  - `AUTHENTICATED` (from `apps.iam.catalog`) means any signed-in member.
  - Two tests enforce this (automated, `apps/iam/tests/test_authz.py`): every action declares a
    permission, and no `/api/web/` view replaces `HasTenantPermission` (a library view did, and
    published the schema).
- **Scope by branch in a selector:**

  ```python
  def get_queryset(self):
      return selectors.visible_loans(self.request.actor)
  ```

  The service checks the write again with `actor.require(code, branch=...)`.

## Requests

- **Parse with a write serializer** (`serializers.Serializer`, not the model serializer). Then
  call one service with an `XInput`, and return the result through the read serializer:

  ```python
  @idempotent
  def create(self, request):
      payload = LoanWriteSerializer(data=request.data)
      payload.is_valid(raise_exception=True)
      d = payload.validated_data
      loan = services.grant_loan(services.LoanInput(employee_id=d["employee"], ...),
                                 actor=request.actor)
      return Response(LoanSerializer(loan).data, status=201)
  ```

- **Serializers live in `serializers.py`,** next to the views (`api/serializers.py`, or the app's
  `serializers.py` in an app with a single `api.py`), never in a view file. `api/fields.py` holds
  reusable field types. `tests/test_repo_hygiene.py` enforces this.
- **No business logic in the view or serializer.** Field-level shape checks belong in the
  serializer (type, required, max length). Business rules belong in the service.
- **Decimals:** clients send them as strings (`"18392.85"`). The renderer writes every Decimal
  as a string (`apps/core/api/renderers.py`), and JSON never contains floats.

## Idempotency

Every action that moves money is decorated with `@idempotent`
(`apps/core/api/idempotency.py`):

| Situation | Result |
|---|---|
| No `Idempotency-Key` header, or longer than 64 characters | `400 IDEMPOTENCY_KEY_REQUIRED` |
| First request with a key | runs; a 2xx response is stored |
| Same key again, same path | the stored response, with `Idempotent-Replay: true` |
| Same key, still running | `409 IDEMPOTENCY_IN_PROGRESS` |
| Same key, another path | `409 IDEMPOTENCY_KEY_REUSED` |
| The action failed (non-2xx or exception) | the key is released; retry with the same key |

Keys are per tenant and user.
- **Clients:** `api()` creates a UUID per call unless given `idempotencyKey`. Screens that
  retry the same act keep one key for it.
- **Known gap:** keys don't compare the request body and never expire.

## Responses

**Success:** the resource as JSON (fields from the read serializer), `200`, or `201` on create.

```json
{"id": 41, "number": "01-EX-2026-000003", "status": "posted", "amount": "1500.00",
 "currency": "EGP", "business_date": "2026-10-24", "category": {"id": 2, "name": "Rent"}}
```

**Lists** are paginated (`apps/core/api/pagination.py`): `?page=`, `?page_size=` (default 25,
maximum 100).

```json
{"count": 132, "next": "https://acme.example.com/api/web/loans/loans/?page=2",
 "previous": null, "results": [ ... ]}
```

**Filtering** uses `django-filter` through `filterset_fields`, e.g.
`?status=posted&business_date__gte=2026-10-01`. Declare the fields a list may be filtered on.
Don't hand-parse query strings.

## Errors

Every error from an API view has one shape (`apps/core/api/exceptions.py`):

```json
{"error": {"code": "VALIDATION_ERROR",
           "message": "Please correct the highlighted fields.",
           "fields": {"amount": ["Must be greater than zero."]},
           "request_id": "8f0c2b6e3a1d4c59"}}
```

| Raised in the service | HTTP | `code` |
|---|---|---|
| `ValidationError(msg, fields={...})` | 400 | `VALIDATION_ERROR` (or the code given) |
| DRF serializer validation | 400 | `VALIDATION_ERROR`; nested `fields` keep their shape (`{"lines": [{}, {"amount": ["…"]}]}`) |
| not signed in | 401/403 | `NOT_AUTHENTICATED` |
| `PermissionDenied` / missing permission | 403 | `PERMISSION_DENIED` |
| `NotFound` | 404 | `NOT_FOUND` |
| `Conflict` (stale state, idempotency) | 409 | `CONFLICT` or specific |
| `DomainError(msg, code="SALES_DISCOUNT_LIMIT")` | 422 | the specific code |
| over the client's request limit | 429 | `THROTTLED`, with `Retry-After` |
| anything unexpected | 500 | **HTML page today** |

Rules:
- **`message` is safe for the user, translated, and never contains a stack trace, SQL or
  internal ids.** Unexpected errors are logged with their traceback in Console → Errors; the
  client gets only the `request_id` to quote.
- **Give a `DomainError` a specific, stable `code`**: clients and tests branch on the code,
  never on the message text.
- **Field names in `fields` are the request's field names**, so `[data-error-for="amount"]`
  finds them.

## The schema

`GET /api/web/schema/` returns the OpenAPI schema (drf-spectacular) to signed-in members. Hand-
written `APIView`s and `@action`s may be incomplete there. Add `@extend_schema` when an
endpoint is meant for other clients.

## Checklist for a new endpoint

- [ ] Route in the app's router, plural noun, action as a sub-path.
- [ ] `required_permissions` for every action; branch-filtered `get_queryset`.
- [ ] Write serializer → one service call → read serializer.
- [ ] `@idempotent` if it moves money.
- [ ] Errors raised as `apps.core.errors`, with a specific code for business rules.
- [ ] Tests: success, validation error, permission refused (and branch refused), replay with
  the same key.
