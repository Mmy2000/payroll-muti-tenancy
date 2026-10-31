# Architecture standards

How the code is organised, and where a new piece of code goes. Every app follows this.
`tests/test_architecture.py` enforces what a machine can check. The decision and the reasons are
in [ADR-105](../decisions/ADR-105-one-app-structure.md).

## The layers of an app

A request passes down through these, and only downwards:

```
api/ or web/      parse the request, render the answer. No rules, no queries.
   |
services          one business act each: permission, transaction, writes, events.
   |      \
selectors  validators   reads; checks that need data.
   |      /
models            fields, constraints, indexes, small display helpers.

domain/           pure calculations. Any layer may call it; it calls none of them.
```

## App layout

Every app has the same shape. Only the first group is required: a file exists when the app has
something to put in it, never to complete the picture.

```
apps/<app>/
  apps.py            AppConfig; ready() registers what the app contributes
  models.py          fields, constraints, indexes, display helpers
  permissions.py     register_permissions(...)

  services.py        writes. Becomes services/ past about 300 lines, or with several topics
  selectors.py       every read, including visible_* (what an actor may see)
  validators.py      checks that read data and raise ValidationError
  domain/            pure calculations: no ORM, no request, no translation of data
  events.py          the domain events this app publishes
  handlers.py        what this app does when another app's event happens
  jobs.py            @task / daily(...)

  api/               the browser's JSON API
    serializers.py     parsing and shaping JSON; every Serializer class lives here
    views.py           ViewSets with required_permissions
    urls.py            the router. config/api_urls.py includes it
  web/               pages
    views.py           page views with @permission_required
    forms.py           Django forms
  templatetags/  templates/<app>/  management/  migrations/  tests/
```

The two names people look for are always the same two places: `api/` is JSON, `web/` is HTML. A
big `views.py` or `serializers.py` becomes a package with the same name. Other modules (an
adapter such as `messaging/gateways.py`, a protocol such as `devices/protocol.py`) stay at the top
of the app under a name that says what they are.

`apps/mobile` has two APIs, so it has `api/v1/` (PayRole's contract for the app, ADR-104) and
`api/web/` (what the browser calls). `apps/platform/console` serves staff pages only, so it has
`web/` and no `api/`.

## Where code goes

| Kind of code | Goes in | Never in |
|---|---|---|
| A business act: what may happen and what it changes | `services` | views, serializers, forms, templates, JS, signals, `save()` |
| A read used by a view, a report or a service | `selectors.py` | views, services |
| What an actor may see (`visible_*`) | `selectors.py` | views, services |
| A check that reads the database | `validators.py` | views, serializers |
| A check on one form or payload's own values | the serializer or form | services |
| A pure calculation (a tax band, a working day) | `domain/` | anywhere it gets copied |
| Parsing and shaping JSON | `api/serializers.py` | views, services |
| Rendering a page | `web/views.py` and templates | services |
| A route of the browser's API | the app's `api/urls.py` | views |
| A route of a page | `config/urls.py` | the apps |
| A permission code | the app's `permissions.py` | strings invented in a view |
| Background work | a `@task` in `jobs.py`, queued with `enqueue()` | threads, `on_commit` sends |
| A reaction in another app | `handlers.py`, on a domain event | a direct import of that app |
| A document number | `apps.core.sequences.allocate_number` | `max(number) + 1` |

### Views

A view does four things: read the input, call a selector or a service, turn the result into a
response, say which permission it needs. It holds no queries and no writes, so the same act can
be called from a job, an import or a test.

```python
class LoanViewSet(ScopedViewSet):
    required_permissions = {"create": MANAGE}

    def create(self, request):
        payload = LoanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        loan = services.create_loan(LoanInput(**payload.validated_data), actor=request.actor)
        return Response(LoanSerializer(loan).data, status=201)
```

### Selectors

Plain functions that return querysets, rows or small dataclasses. They never write.

```python
def visible_loans(actor, code: str = VIEW) -> QuerySet[Loan]:
    return scoped_to_branches(Loan.objects.select_related("employee"), actor, code)
```

A selector takes filters as arguments, not a request. Choice lists for a form are selectors too.

### Validators

A function that checks one rule against the data and raises `ValidationError(fields=...)`, or
returns the clean value. Services call them in the transaction, after locking what they check.
Extract one when a check is big enough to name or is used twice. A one-line check stays in the
service.

### Service functions

This is the shape every write follows:

```python
@dataclass(frozen=True)
class LoanInput:                 # what the caller provides, as plain values
    employee_id: int
    amount: Decimal
    ...

def create_loan(data: LoanInput, *, actor=None) -> Loan:
    with transaction.atomic():                        # 1. one transaction for the whole act
        employee = get_employee(data.employee_id, actor, MANAGE, lock=True)
        if actor is not None:
            actor.require(MANAGE, branch=employee.branch_id)   # 2. permission, per branch
        check_room_for_loan(employee, data.amount)    # 3. validate, after locking
        loan = Loan.objects.create(...)               # 4. write
        publish(LoanCreated(loan.pk))                 # 5. tell who cares
    return loan
```

Rules:
- **Keyword-only arguments.** Pass an `XInput` dataclass when there are more than about four
  values.
- **`actor=None`** means a trusted internal caller (a test, a job, another service that has
  already checked). The API always passes `request.actor`.
- **The service opens its own `transaction.atomic()`.** Don't rely on the request transaction:
  it commits on 4xx responses.
- **Lock before you check** anything another request could change between your check and your
  write. Use `select_for_update(of=("self",))`, so only the row you mean is locked, not the rows
  it joins. Lock several rows in a stable order (by id).
- **Raise the errors from `apps.core.errors`:**
  - `ValidationError(message, fields={"field": [...]})` for input.
  - `DomainError(message, code="APP_SPECIFIC_CODE")` for a broken rule.
  - `NotFound` and `PermissionDenied`.
  - `Conflict` for a stale state.
- **Return the model.** The caller serialises it.

### Size

- A file past about 300 lines usually holds more than one topic: split it by topic. A file that
  really is one thing stays whole (the pay engine; the tenants' models).
- A function that needs "and" to describe it does two things.

## Dependencies between apps

Apps form layers. An app imports its own layer and the ones above it in this table, never below.

The table is completed in the last phase of ADR-105.

- `core` knows no business app. What it needs from one is given to it through a registry.
- **A lower app needs a higher one to act?** Publish a domain event, or fill a registry from
  `ready()`. Don't import upward, not even inside a function.
- **Import public names only.** Never `_private` functions from another module.
- Imports inside functions are for heavy or optional libraries. They are not a way round a cycle.

### Registries

The main way apps plug into something below them. An app adds itself, and the owner iterates:

```python
# apps/evaluations/apps.py
def ready(self):
    from apps.core.documents import register_document
    register_document("evaluations.Evaluation", "evaluation", _("Evaluation"))
```

Use an existing registry before creating one: permissions and limits (`iam.catalog`), features
(`platform.tenants.features`), jobs (`platform.jobs.registry`), documents (`core.documents`),
reports (`reports.registry`), seeding (`core.seeding`), audit labels.

### Domain events

`apps/core/events.py` is an in-process Observer. A service publishes what happened, and
`handlers.py` in another app reacts, inside the same transaction. The publisher knows nothing of
who listens. That is how a leave decision reaches the notifications without `attendance` importing
`notifications`.

## Patterns in use

These exist and solve a real problem here. A new pattern needs an
[ADR](../decisions/README.md).

| Pattern | Problem it solves | Where |
|---|---|---|
| **Service layer** (functions) | One business act, callable from the API, a job, an import or a test | `services` in each app |
| **Selector** | One place for reads, so a query isn't written twice | `selectors.py` |
| **Input object** | Many values, built once, easy to make in a test | frozen `XInput` dataclasses |
| **Registry** | Apps add to a list its owner can't import them for | see [registries](#registries) |
| **Observer** | A reaction in another app, with no dependency on it | `core/events.py`, `handlers.py` |
| **Strategy** | Interchangeable implementations of one interface | WhatsApp gateways (`messaging/gateways.py`), the frontend's pickers |
| **Outbox** | A side effect only if the work commits | `apps/platform/jobs`: `enqueue` inside the transaction |
| **Idempotency key** | A double click never acts twice | `apps/core/api/idempotency.py` |

We do **not** use repositories over the ORM, or service classes and dependency injection
(ADR-105). `TenantScopedModel` is already the persistence abstraction: it scopes every query to
the client and fails closed.

## SOLID, applied here

- **Single responsibility.** A service does one business act; a selector answers one question; a
  view parses and renders. Split a function when it has more than one reason to change.
- **Open/closed.** Extend through registries, events and strategies, not by editing a central list.
- **Liskov.** A subclass of `TenantScopedModel` or a gateway keeps the base's contract.
- **Interface segregation.** Services take the values they need (an `XInput`), not a request.
  Selectors return querysets or small dataclasses.
- **Dependency inversion.** Lower layers define the registry or the event; higher layers plug in.
  Don't invert with abstract base classes unless there are two real implementations.

**When is a new abstraction justified?** When the same logic exists in three places, when two apps
must cooperate without a cycle, or when a test can't be written without it. Otherwise, write the
plain function.

## Frontend

The full rules are in README "Frontend assets". In short:

- **Templates** use the component classes in `assets/css/app.css` and logical utilities
  (`ms-`, `text-start`), so one template serves RTL and LTR.
- **One ES module per page** in `static/<app>/js/`. It reads URLs and translated text from
  `data-*` attributes or `json_script`.
- **Shared helpers** live in `static/core/js/`: `api()` for every request, `toast()` from `ui.js`.
  Don't write another `fetch` helper.
- **Plain forms** use `<form data-api-form data-endpoint=…>`. Errors appear in
  `[data-error-for="field"]`.
- **Icons** are `{% icon "name" %}`. A new name goes in `assets/copy-assets.mjs`, then
  `npm run build`.
- **Build output is committed:** `static/core/css/app.css`, `apps/core/ui_icons.json` and
  `static/vendor/`.

## Recording decisions

A decision that is hard to reverse or that others must follow gets an ADR in
[docs/decisions/](../decisions/README.md): a new registry, a new dependency, a change to tenancy,
money or identity rules, a new process or service.
