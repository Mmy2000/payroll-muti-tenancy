# Coding conventions

How code in this repository is written. **Automated** means a check fails, locally
(`python ops/check.py`) and in CI. Everything else is checked in review.

## Formatting and lint

- **ruff** with the rules in `pyproject.toml`: `E F W I B UP DJ S608`, line length **100**,
  target Python 3.12. Automated.
- **There is no auto-formatter.** The code has a consistent hand style, and `ruff format` would
  rewrite 540 files ([ADR-019](../decisions/ADR-019-lint-without-formatter.md)). Match the code
  around you:
  - Continuation lines align with the opening bracket.
  - Short related statements may share a line (`a, b = x, y`).
  - Blank lines separate the steps of a function, and section comments mark parts of a long
    module (`# --- punching ---`).
- **Imports** are sorted by ruff (`I`): standard library, third party, `apps.`, local.
  - Use `from __future__ import annotations` in modules with type hints.
  - Import cross-app names at module level unless the module is heavy, optional (a feature
    app), or the import would create a cycle. The cycle case is debt, see
    [architecture standards](architecture.md#dependency-direction).
- **`.editorconfig`:** UTF-8 **without BOM** (automated: `tests/test_repo_hygiene.py`), spaces,
  4 for Python, 2 for HTML/JS/CSS, final newline. On Windows, edit with an editor or Python,
  never PowerShell 5.1's `Set-Content -Encoding utf8`, which writes a BOM.
- **Template comments** `{# … #}` must close on the same line; use `{% comment %}` for longer
  ones (automated).

## Naming

| Thing | Convention | Example |
|---|---|---|
| Modules, functions, variables | `snake_case`, named after the business act | `grant_loan`, `void_trade_sale`, `ensure_cash_available` |
| Classes, models | `PascalCase`, singular | `PayrollRun`, `LeaveRequest` |
| Input objects | `<Thing>Input`, frozen dataclass | `LoanInput`, `RunInput` |
| Constants | `UPPER_SNAKE` | `MAX_INSTALLMENTS = 120` |
| Private helpers | leading `_`, used only in their module | `_field_error` |
| Permission codes | lower case, dotted `app.object.action` (automated: `test_catalog_codes_are_well_formed`) | `loans.loan.manage`, `expenses.void` |
| Error codes | `APP_UPPER_SNAKE` | `MOBILE_LOGIN_EXISTS`, `MOBILE_QR_LEFT` |
| URL names | `kebab-case` | `employee-new`, `console-tenant-settings` |
| Document number prefixes | 2–3 capitals, unique (`allocate_number`) | `PRL` |
| Database constraints and indexes | `<app>_<model>_<what>_<kind>` | `mobile_device_once_uniq`, `mobile_link_active_idx` |
| Tests | `test_` + what happens, in words | `test_a_manager_cant_get_into_a_login_above_their_own` |

**Use the domain words**, the ones the screens and [the PayRole rules](../payrole-rules.md) use.

## Functions and modules

- **Aim for functions under about 60 lines, with cyclomatic complexity under 15.** If a
  function grows past that, extract named steps (`ruff check apps --select C901` lists them).
- **More than about four parameters:** make them keyword-only (`*,`) or pass an `XInput`.
- **Don't nest conditions three or more deep.** Return early, or raise.
- **One module, one subject.** Split a module past about 300 lines by business act, as
  `apps/payroll/services/` does with `runs.py`, `lifecycle.py` and `calendars.py`.
- **No magic numbers.**
  - Money precision comes from `apps.core.numeric` (`MONEY`, `round_money`, `quantize`).
  - Anything else gets a named constant with a comment saying where the value comes from.

## Numbers, text and time

- **Money, weights and rates are `Decimal`, always.**
  - Build them with `quantize(value, MONEY)` / `to_decimal`; these refuse `float`.
  - Round only through `apps.core.numeric`.
  - Never use `float()`, `round()` on money, or `FloatField` (automated:
    `tests/isolation/test_model_coverage.py::test_no_float_fields`).
- **Every user-visible string is English source text**, wrapped in `_()` / `gettext_lazy` /
  `{% translate %}`, and translated to Arabic in `locale/ar/LC_MESSAGES/django.po` (automated:
  `ops/i18n/messages.py check`). Write `%(name)s` placeholders, not f-strings, inside `_()`.
- **Stored text stays language-neutral.** Store codes and user input, and translate when
  displaying.
- **Dates:**
  - `timezone.localdate()` is the business date; `timezone.now()` is a moment.
  - A job runs in its client's time zone (the worker sets it).
  - Never write today's year into a test: use `conftest.this_year()`.

## Comments and docstrings

- **Module docstring:** what this module is for, in the business's terms.
- **Function docstring** for any public service or helper whose name doesn't say everything:
  - One sentence on what it does.
  - Then the non-obvious rules: what it refuses, what it locks.
- **Comments say why, not what.** Write them for a reason a reader couldn't guess. Good
  examples from the code:
  - `# Not atomic: a failed run's record must outlive the failure`
  - `# drf-spectacular sets its own permission_classes, which would skip the project's default`
- **ADR-nnn** refers to a decision. Cite one when the code implements it: that is how a reader
  finds the reasoning.
- **No commented-out code and no TODOs.** Use git for old code, and fix a known problem or
  open an issue for it.

## Errors

- **Raise `apps.core.errors`** (`ValidationError`, `DomainError`, `NotFound`,
  `PermissionDenied`, `Conflict`). Never raise a bare `Exception`.
- **Catch the narrowest exception** that the code can handle. `except Exception` is allowed
  only where everything is recorded or re-raised: the worker, error logging, the backup. Mark it
  with `# noqa: BLE001 - <why>`. A broad catch that hides a value is a bug (audit O13).
- **Never `pass` on an exception**, and never return a default that looks like a real result.

More detail: [errors and logging](errors-and-logging.md).

## Types

- **Annotate the signatures of public functions**, the return type included (`-> ExpenseVoucher`).
  Locals don't need annotations.
- **There is no type checker in CI yet.** Annotations document the code; keep them true.

## Dead and deprecated code

- **Delete code with no callers in the same pull request** that removes its last caller. Prove
  it with a grep across `apps config ops tests templates static`.
- **Backward compatibility is needed for:**
  - The mobile app's legacy endpoints (`/api/auth/`, `/Sup/api/`, `/Sup1/api/`): their response
    shapes are fixed on purpose.
  - Data already stored (migrations).
  - Anything a client has saved (custom document HTML, label designs).
  
  Change these only with a migration path in an ADR.
- **Mark deprecated code** with a comment giving the replacement and the register ID, and
  remove it when the last user moves.
