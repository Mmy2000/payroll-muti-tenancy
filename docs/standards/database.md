# Database and data integrity standards

PostgreSQL is where the hardest rules live. Each rule below is enforced by the database and a
test, so it holds even when application code is wrong. Keep it that way: a new invariant goes
into a constraint or trigger when it can, not only into Python.

## Models

- **Every tenant-owned model inherits `TenantScopedModel`** (`apps/core/models.py`).
  - It must declare an index or unique constraint **starting with `tenant`**.
  - Business documents inherit `Document`: number, status, branch, business date, posted/voided
    by and at.
  - Automated: `tests/isolation/test_model_coverage.py`.
- **Platform models** (no tenant) live only in `apps/platform/*`.
- **Fields:**
  - Money, weights and rates are `DecimalField`, never `FloatField` (automated). Use the
    precisions the rest of the schema uses, matching `apps/core/numeric.py`:

    | Value | Field | Rounding constant |
    |---|---|---|
    | Money | `max_digits=18, decimal_places=2` | `MONEY` |
    | Fractions (discount, fee, commission: 0.125 = 12.5 %) | `decimal_places=6` for new fields | `RATE` |

    Existing fraction fields use 4 or 6 decimal places (`inventory` discount limits and `hr`
    commission rates use 4). Don't change them without a migration and a reason.

  - Text that may be empty is `blank=True` with `""`, not `null=True`.
  - Nullable foreign keys mean "optional", and the model says when.
- **Relationships:**
  - `on_delete=models.PROTECT` for anything financial or referenced by a document.
  - `CASCADE` only from a document header to its own lines.
  - `related_name="+"` when the reverse relation isn't needed.
- **Constraints:**
  - Express invariants as `CheckConstraint` / `UniqueConstraint`, not just Python checks. For
    example, a date that ends after it starts, or an amount above zero.
  - Use partial unique constraints for "one default per branch and currency".
  - Name them `<app>_<model>_<what>_<kind>`.
- **Indexes:**
  - Index the columns lists and reports filter on, starting with `tenant`. Documents use
    `(tenant, branch, -business_date)`.
  - Look at the query before adding one: an index slows every write.

## The tables that must never change in place

- `audit_*`: written only by triggers.
- Approved payroll: a run's payslips don't change after approval. A correction is a reversal
  (`apps/payroll/services/lifecycle.py`), and a locked period refuses changes to what it paid
  (`apps/core/locks.py`).

## Each new tenant model's migration

```python
from apps.audit.triggers import AuditModel, GuardTenantFKs
from apps.core.tenancy.rls import EnableTenantRLS

operations = [
    EnableTenantRLS("ExpenseRefund"),   # ENABLE + FORCE row-level security + policy (required)
    GuardTenantFKs("ExpenseRefund"),    # refuse foreign keys to another tenant's rows (required)
    AuditModel("ExpenseRefund"),        # master data only: record every change (optional)
]
```

The isolation suite fails if `EnableTenantRLS` or `GuardTenantFKs` is missing, or if the guard
is stale after a new foreign key. Re-run `GuardTenantFKs` in the migration that adds a foreign
key.

Use `AuditModel` for master data: prices, parties, users, roles, holders, accounts, designs.
Don't use it for documents, which have their own history.

## Transactions and concurrency

- **A service opens `transaction.atomic()` around the whole act.** The request transaction
  commits on 4xx, so don't rely on it.
- **Lock before checking** anything another request could change between the check and the
  write.
  - `select_for_update(of=("self",))` locks only that row. Plain `select_for_update()` with
    `select_related` also locks the joined rows (often the branch): avoid it.
  - Lock several rows in a stable order (by id), so two transactions can't deadlock.
- **Numbers come from `allocate_number`** (row-locked counter, gapless, refuses to run outside
  a transaction).
- **External calls** (HTTP, SMTP) never happen inside a transaction that holds locks. Queue a
  job instead: it is part of the transaction (outbox) and runs after commit.
- **A race the database catches** (a unique violation) should become a `Conflict` with a clear
  message, not a 500.

## Queries

- **No N+1 queries.** Use `select_related` for foreign keys you display and `prefetch_related`
  for reverse sets. Use aggregation (`Sum`, `Count`) instead of Python loops over rows.
  - Check: `django.test.utils.CaptureQueriesContext` in a test, or count queries in the
    development toolbar of your choice.
- **Paginate lists.** The API does it by default; web lists use `apps/org/listing.py`.
- **`.raw()`, `.extra()` and string-built SQL are not allowed.** `cursor.execute` takes
  parameters (`%s`) only. Ruff's `S608` flags string-built SQL (automated).

## Migrations

- **Create them with `manage.py makemigrations`, and give them a name:**
  `makemigrations loans --name early_settlement`. Never hand-edit an applied migration.
  - CI fails when models and migrations disagree (`makemigrations --check`).
- **Data migrations:**
  - Use `RunPython(forward, reverse)` with a real reverse, or `migrations.RunPython.noop` when
    there is nothing to undo.
  - Load models with `apps.get_model(...)`.
  - **Never import live application code or constants.** Copy the data into the migration.
- **Run them as the owner role:** `manage.py migrate --database owner`. `payroll_rw` cannot change
  the schema.
- **Make every schema change safe to deploy before the code that uses it**, because the old
  code runs against the new schema during a deploy:
  1. Add the column nullable or with a default, deploy, and backfill in a separate data
     migration if the table is large.
  2. Then make the code use it.
  3. Remove an old column in a later release, after no code reads it.
  - Renaming a column is add, copy, switch, drop over two releases.
- **Big tables** (punches, tracking points, traffic):
  - Don't add a non-null column without a default.
  - Build new indexes with `AddIndexConcurrently` in a non-atomic migration.
  - Test the migration's time on a copy of production data.
- **Review:** the reviewer reads the generated SQL (`manage.py sqlmigrate app 00nn`) for every
  migration that changes a table with data.
- **Rollback:** know how you'd undo it before merging. Usually that's reverse migration plus
  the previous release; for a destructive one, the backup. Say which in the pull request.

## Test data

- Tests run against PostgreSQL (`config/settings/test.py`, database `test_gweb`), connected as
  `payroll_owner`. That role is **not a superuser**, so row-level security applies in tests exactly
  as in production (automated: `test_test_connection_is_not_a_superuser`).
- Build data through services, the way users do: `make_tenant` provisions a full tenant, and
  `make_employee` makes a real employee. Don't insert rows that bypass the services' rules.
- There are no fixtures or seed files. Reference data (roles, leave types, adjustment types) is
  seeded when a client is provisioned (`apps/core/seeding.py`).

## Backups

Developers: never point a local
`.env` at a production database. Restoring production data locally needs the same encryption
keys, and copies customers' personal data onto your machine.
