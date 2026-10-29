# Payroll SaaS: rebuild plan

Rebuild of the single-company PayRole system (`D:\software house\PayRole`) as a multi-tenant SaaS,
following the structure and standards of Gweb (`D:\software house\Saas_ERP`).

## Decisions

| Topic | Decision |
|---|---|
| Source system | PayRole: its business rules are ported, its code is not |
| Reference structure | Saas_ERP: tenancy, layering, frontend conventions, docs/standards |
| Django | 6.x (Saas_ERP code was written for 5.2; adapt and verify while porting) |
| Tenancy | One PostgreSQL database, `tenant_id` on every tenant table, row-level security, tenant from the host |
| Frontend | Tailwind CSS v4 (latest 4.x), server-rendered templates, vanilla ES modules, AJAX through `api.js` / `forms.js` |
| PayRole bugs | Fixed, not reproduced (see "Behaviour changes") |
| Mobile app API | Kept as it is: same paths, request and response shapes, JWT |
| Existing data | None migrated: every tenant starts fresh |
| PDFs | HTML rendered by Playwright (headless Chromium), as in Saas_ERP |

## Architecture

Same layering as Saas_ERP (`docs/architecture/overview.md`, `docs/standards/architecture.md` there):

- **Models** are thin: fields, constraints, display helpers. Every tenant model inherits
  `TenantScopedModel`; documents inherit `Document` (draft → posted → voided, gapless number).
- **Services** (`services.py`) hold every business rule: keyword arguments or a frozen `XInput`
  dataclass, `actor.require(...)`, their own `transaction.atomic()`, row locks before checks,
  errors from `apps.core.errors`.
- **Domain** (`domain/`) holds pure calculations with no ORM: the payroll engine, tax, rates.
- **Selectors** hold reads shared by several screens.
- **API** (DRF) parses and serializes; **web views** read and render. Every write from the browser
  goes through the API over AJAX.
- **No business logic in signals, views, templates or JS.** No money arithmetic in JS.

### Tenant isolation (copied from Saas_ERP `apps/core/tenancy`)

1. `TenantResolutionMiddleware`: host → tenant; platform hosts get the console.
2. `tenant_context(tenant_id)`: ContextVar + `SET LOCAL app.tenant_id`, inside a transaction.
3. `TenantScopedModel` / `TenantManager`: queries fail without a tenant context.
4. PostgreSQL: `ENABLE` + `FORCE ROW LEVEL SECURITY` per table (`EnableTenantRLS`), a trigger
   refusing cross-tenant foreign keys, and an application role that cannot bypass RLS.

An isolation test suite checks every tenant model has RLS and that one tenant cannot read or
write another's rows.

### Apps

| Layer | App | Owns | Replaces in PayRole |
|---|---|---|---|
| Foundation | `core` | Tenancy, base models, errors, API plumbing (envelope, pagination, idempotency), numbering, Decimal helpers, i18n | — |
| | `iam` | Users, memberships, roles, permission catalog, `Actor` (branch-scoped) | `Users` permissions, "first branch sees all" |
| | `org` | Tenant profile (name, logo, time zone, phone region, attendance switches), branches, departments | `com`, `Br1`, `Pfn`, global settings |
| | `audit` | Audit trail | `Notif.SystemLog` + audit signals |
| Master data | `employees` | Employee card; effective-dated compensation (salary, daily/hourly rates, multipliers) and work schedule (shift, days off) | `Pfe1`, shift change (GHA18) |
| | `policies` | Lateness and overtime policies with band rows, tax tables with bracket rows, insurance rates, public holidays: all effective-dated | `Pfn` bands, `Ptax`, `Pins`, `Pvac` |
| | `compensation` | Pay item catalogue (addition/deduction, fixed/daily, taxable) and assignments to employees, departments or branches | `Pfn1`, `Pfe2` (`so1`/`so2`) |
| Transactions | `attendance` | Punches, day records (absent, weekly off, leave), leave requests and balances, hourly permissions, ZK devices (ADMS), GPS tracking, phone biometric binding | `zkk` |
| | `loans` | Advances, loans, installments | `Pfe2` (`so3`/`so4`), `Pfe2_i` |
| | `adjustments` | Incentive and penalty types; incentives and penalties | `Pa1`, `Pa2`, `Pfe5a` |
| | `payroll` | Payroll runs (documents), payslips with input snapshot, payslip lines, daily breakdown; `domain/` calculation engine | `Salary` |
| | `evaluations` | Annual evaluations | `Eva` |
| Outputs | `reports` | Report registry and reports | GH*1x report screens |
| | `printing` | Printable documents, PDF (Playwright), Excel export | per-app `draw_header` + reportlab |
| | `messaging` | WhatsApp gateway (per-tenant sender), payslip sending through jobs | `whatsapp_gateway` |
| | `notifications` | In-app notifications | `Notif.Notification` |
| | `mobile` | The mobile app's API, unchanged contract | `Api` |
| Platform | `platform.tenants` | Tenants, domains, plans, features, provisioning, ZK device serial registry | — |
| | `platform.console` | Platform staff screens | — |
| | `platform.jobs` | Job queue (PostgreSQL table), worker, schedules | (none: was synchronous / manual) |

### Design patterns

| Pattern | Used for |
|---|---|
| Service layer + `XInput` | Every write |
| Strategy | Amount methods (fixed, % of salary, days × daily rate, hours × hourly rate); attendance sources (ZK, mobile, manual, Excel); WhatsApp gateways |
| Pipeline of calculators | Payroll engine: day pay → overtime → lateness → leave and holidays → pay items → incentives/penalties → advances and installments → insurance → tax → net. Each calculator is pure and tested alone |
| Quote then post | `plan_payroll()` previews with no side effects; `post_payroll()` recomputes and, in one transaction, numbers the run, saves payslips and settles installments. `void_payroll()` reverses it |
| Snapshot | A payslip stores the rates and policies it used; reprints never change |
| Registry | Permissions, reports, jobs, printable documents |
| Outbox | WhatsApp and notifications are queued in the same transaction as the work |
| Template method | One exporter for PDF and Excel; reports supply data only |
| Idempotency key | Every API action that posts or pays |

## Frontend

- Tailwind CSS v4 built from `assets/css/app.css` into `static/core/css/app.css`; design tokens,
  per-tenant accent colour, dark mode through tokens (no `dark:` in templates).
- Logical utilities (`ms-`, `pe-`, `text-start`) so one template serves Arabic (RTL) and English.
- One ES module per page in `static/<app>/js/`; shared helpers in `static/core/js/`:
  `api()` for every request (CSRF, idempotency key, error envelope), `forms.js`
  (`<form data-api-form data-endpoint>`, field errors in `[data-error-for]`), `ui.js`, `loading.js`.
- No jQuery, Bootstrap or inline scripts. Libraries: Tom Select, Lucide icons, Chart.js, Leaflet.
- Translation with Django gettext `.po` files; PayRole's `locale/ui_en.json` (~1,640 entries) is
  converted as a starting point.
- Readable URLs (`/employees/12/`) instead of screen codes (`/Enp/GHA12a`).
- Web AJAX API under `/api/web/`; `/api/v1/` stays reserved for the mobile app's contract.

## Multi-tenant specifics

- **Time zone, phone region and attendance switches** (biometric, tracking, geofence) are per
  tenant, in the tenant profile. `USE_TZ = True`.
- **ZKTeco devices** push to `/iclock/` and do not know the tenant. A platform-level registry maps
  each device serial number to its tenant; the request then runs in that tenant's context.
- **Mobile app:** the API contract stays the same, and each client's app uses its own URL
  (the tenant's subdomain or custom domain), so the tenant comes from the host like every other
  request. Tokens carry the tenant and are refused on another tenant's host.
- **Numbering** uses `allocate_number` (row-locked, gapless) instead of `max + 1`.

## Features (switched on and off per client)

Every module is a feature that the platform admin switches on or off from the console, for a
plan or for one client. Only the platform admin does this; a client's own users, Owners
included, cannot change their features. Copied from Saas_ERP `apps/platform/tenants/features.py`,
extended with dependencies, and filled by each app rather than one central list
([ADR-102](decisions/ADR-102-features-registered-by-apps.md)). The
platform admin switches them in the console (client → Features, Plans, Features).

**How a feature's state is decided:**
1. the client's own setting (console → client → Features), if saved;
2. else the client's plan's setting (console → Plans), if saved;
3. else the feature's code default.

A feature is effectively on only if everything it `requires` is on as well.

**What "off" does, with no per-screen code:**
- **Permissions:** a feature owns permission code prefixes. When it is off, those permissions
  count as not granted for everyone in the workspace, Owners included (`Actor.can`). Sidebar
  links, buttons, dashboard blocks, pages and API endpoints that need them disappear or refuse.
- **Payroll:** each calculator in the payroll pipeline declares its feature. Calculators for
  features that are off are skipped (no overtime, no tax…). The payslip snapshot records which
  features were on, so a reprint matches the original.
- **Background work:** jobs and schedules of a feature that is off do not run for that client.
- **Integrations:** the mobile API answers its normal "forbidden" response; ZK devices of a
  client with devices off are refused.
- **Data is kept.** Switching a feature back on shows everything as it was.

**Features (first list; refined per phase):**

| Feature | Covers | Requires | Default |
|---|---|---|---|
| `employees` | Employee cards, departments, branches, salaries | — | always on (core) |
| `payroll` | Payroll runs, payslips | `employees` | always on (core) |
| `attendance` | Manual attendance, day records, attendance reports | — | on |
| `attendance_import` | Excel attendance import | `attendance` | on |
| `zk_devices` | ZKTeco devices (ADMS push), punch log | `attendance` | off |
| `leave` | Annual leave requests and balances | `attendance` | on |
| `permissions_hourly` | Hourly permissions ("إذن") | `attendance` | on |
| `lateness` | Lateness policies and deductions | `attendance` | on |
| `overtime` | Overtime policies and pay | `attendance` | on |
| `public_holidays` | Public holidays and holiday pay | — | on |
| `pay_items` | Allowances and add/deduct items | — | on |
| `incentives` | Incentive types and entries | — | on |
| `penalties` | Penalty types and entries | — | on |
| `advances` | Salary advances | — | on |
| `loans` | Installment loans | — | on |
| `insurance` | Social insurance rates and deductions | — | on |
| `income_tax` | Tax tables and deduction | — | on |
| `evaluations` | Annual evaluations | `employees` | on |
| `reports_export` | PDF and Excel export of reports | — | on |
| `whatsapp` | Payslips over WhatsApp from the client's number | — | off |
| `mobile_app` | The mobile app (sign-in, punches, leave, notifications) | `attendance` | off |
| `biometric` | Phone biometric binding required for punches | `mobile_app` | off |
| `gps_tracking` | GPS tracking during shifts, live map | `mobile_app` | off |
| `geofence` | Punches only inside the branch area | `mobile_app` | off |

`employees` and `payroll` cannot be switched off, so they are not registered as features. How
many branches a client may have is the plan's (or client's) branch limit, not a feature.
PayRole's global switches
(`ATTENDANCE_REQUIRE_BIOMETRIC`, `ATTENDANCE_REQUIRE_TRACKING`, `ATTENDANCE_ENFORCE_GEOFENCE`)
become the `biometric`, `gps_tracking` and `geofence` features.

**Adding a feature** = in the module's `permissions.py`, register its permission codes
(`register_permissions`) and its `register_feature(Feature(...))` listing their prefix and its
`requires`; declare the feature on any calculator or job it owns. It then appears for the
platform admin on its own.

## Behaviour changes (PayRole bugs fixed)

| PayRole behaviour | New behaviour |
|---|---|
| Daily/monthly flag of allowances applied inverted (`Salary/payroll.py:321` vs `Allow/views.py:339`) | Daily items are multiplied by days worked; monthly items are fixed |
| Punches from the external attendance API (`/zkk/api/attendance/`) are ignored by payroll (`k` not set) | Every attendance source counts the same |
| Overtime bands (GHA14) and "overtime starts after" are configured but unused | Overtime policy bands are applied |
| Weekly-paid employees are paid as monthly ÷ 30 | Weekly and biweekly runs on their own periods; monthly items split by days (or whole in the week of the 1st), installments whole in the week of the 1st (docs/payroll-design.md §4) |
| Money stored as integers in payroll lines | `Decimal` everywhere, rounding only through `core.numeric` |
| Salary and shift changes overwrite the card | Effective-dated history; payroll uses the values valid on each day |
| Payroll creates attendance rows and marks installments while calculating | A draft has no side effects; approval settles installments and advances; reversal releases them |
| Insurance 14 % / 26 % when no rates are set | No rates: nothing deducted and approval blocked; 0 % is a deliberate setting; the employer share is a cost, not a deduction |
| A paid run is recalculated from today's cards | Approved payslips are frozen with a snapshot of their inputs |
| Logic compares Arabic label strings | Enumerated choices |
| Manual-entry-overrides-device rule lives in a signal | A service rule |
| WhatsApp sends inside the request (60 s timeout) | Queued jobs with retries |
| Synchronous OpenCage geocoding during template rendering | Done in a job, result stored |

## Phases

Each phase ends with its tests passing and ruff clean.

0. **Foundation**: project layout (`config/`, `apps/`), split settings, PostgreSQL roles and RLS,
   `core`, `platform.tenants`, `platform.jobs`, `iam`, `org`, `audit`; base layout, Tailwind
   build, login, tenant isolation suite, pytest, ruff, CI.
1. **Master data**: employees with history, branches, departments, shifts, policies, tax,
   insurance, holidays, pay items, Excel import of employee cards.
2. **Attendance**: manual entry, Excel import, day records, leave requests and balances, hourly
   permissions.
3. **Loans and advances; incentives and penalties; pay item assignments.**
4. **Payroll**: pay calendars and periods (regular and off-cycle), runs (draft, approved, paid,
   reversed), the engine, payslips with snapshots; tests built from worked examples of
   PayRole's rules (with the fixes above).
5. **Reports, PDF and Excel export, printing.**
6. **Integrations**: ZK ADMS, WhatsApp through jobs, mobile API (unchanged contract) with
   biometric proof and GPS tracking.
7. **Evaluations, dashboard, notifications.**
8. **Platform console**: tenant sign-up and provisioning, plans and features, suspension.

## Progress

| Phase | State |
|---|---|
| 0. Foundation | Done (2026-10-28) |
| 1. Master data | Done (2026-10-28). |
| 2. Attendance | Done (2026-10-29). Punches from devices and the mobile app come in phase 6. |
| 3. Advances, loans, incentives, penalties, pay items given | Done (2026-10-29). |
| 4. Payroll | Done (2026-10-29): calendars, regular and off-cycle runs, draft → approved → paid, reversal, frozen payslips, nothing paid twice, locks on what an approved run covers (phases 1–3 now refuse those changes). |
| 4b. History, bulk changes, batches | Done (2026-10-29): History pages read the payroll tables; hourly leave, attendance by hand and working hours for a group with a preview; incentive and penalty batches with drafts, approval, reopening, cancelling and corrections. |
| 5. Reports, PDF, Excel, payslips | Done (2026-10-29): report registry with 14 reports, PDF and Excel export (one exporter, two formats), payslip PDFs, export permission and feature. |
| 6. Devices, mobile app, WhatsApp | Done (2026-10-29): ZK ADMS devices, the mobile API with PayRole's contract (docs/mobile-api.md), notifications, WhatsApp payslips through jobs. |
| 7. Evaluations, dashboard, notifications | Done (2026-10-29): evaluations with their card, the dashboard with server-drawn charts, the bell and the notifications page. |
| 8. Platform console | Done (2026-10-29): sign-up, client page (plan, limits, company settings, domains, features, status), plans, features, traffic, jobs, platform settings, activity. |

## Open questions

