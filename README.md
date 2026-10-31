# Payroll

Multi-tenant payroll, attendance and HR: the rebuild of PayRole as a SaaS, on the foundation of
Gweb (`Saas_ERP`). The plan, decisions and phases are in [docs/PLAN.md](docs/PLAN.md); the rules
new code follows are in [docs/standards/](docs/standards/) and
[docs/decisions/](docs/decisions/README.md). The standards are Gweb's, copied as they are: their
rules apply, but their examples name Gweb's apps (sales, ledger…), which this project doesn't have.

## What exists so far

### Phase 0: foundation

- **Tenancy:** one PostgreSQL database; each client is found from its host
  (`<slug>.<TENANT_BASE_DOMAIN>`), and its rows are isolated by row-level security, a
  fail-closed ORM and same-tenant foreign key triggers (`apps/core/tenancy`, `apps/audit`).
- **Platform:** clients, domains, plans and per-client features with dependencies
  (`apps/platform/tenants`), and a job queue with a worker and schedules (`apps/platform/jobs`).
  Platform staff work in the console on the platform host (`apps/platform/console`).
- **Workspace:** sign-in, users, roles with branch scopes, branches, company settings, the
  history of changes and of sign-ins (`apps/iam`, `apps/org`, `apps/audit`).
- **Frontend:** Tailwind CSS v4, Arabic (RTL) and English, light and dark themes, vanilla ES
  modules; forms post JSON to `/api/web/` over AJAX (`static/core/js/api.js`, `forms.js`;
  nested fields and repeatable rows: `structured.js`).

### Phase 1: master data

- **Employees** (`apps/employees`): the card (national ID encrypted), and effective-dated pay
  (`Compensation`) and working hours (`WorkSchedule`): a change applies from a date and earlier
  months keep their values. Pay has its own permissions (`employees.salary.*`). Excel import,
  all rows or none.
- **Departments** (`apps/org`).
- **Pay policies** (`apps/policies`): lateness and overtime policies with minute bands, income
  tax tables with brackets, social insurance rates, public holidays; pure calculations in
  `domain/`. Features: `lateness`, `overtime`, `income_tax`, `insurance`, `public_holidays`.
- **Pay items** (`apps/compensation`): allowances and deductions, fixed or per day worked.
  Feature: `pay_items`.

### Phase 2: attendance

- **Punches** (`apps/attendance`): raw clock times, append-only in the database; Excel import
  now, devices and the mobile app in phase 6.
- **Day status is computed, never stored** (`domain/days.py`): a chain of rules (not employed →
  manual entry → clock → leave → holiday → weekly off → not yet → absent), with late, early and
  extra minutes. `selectors.evaluate()` reads any employees over any period in six queries; the
  daily sheet, an employee's month and payroll (phase 4) all use it.
- **Manual entries** (`entries.py`): worked / absent / excused / day off for a day, winning over
  the punches without touching them; one by one or for ticked employees at once.
- **Leave** (`leave.py`): leave types (seeded for new clients), requests counted in working
  days, the yearly balance checked on approval. **Hourly leave** (`hourly.py`) within the monthly
  allowance. Both use one state machine (`approvals.py`).
- **Shared**: every request runs in the client's time zone (`apps/core/timezones.py`); Excel
  imports share `apps/core/imports.py` (Template Method) and one page (`apps/core/import_page.py`).
- Features: `attendance`, `attendance_import`, `leave`, `hourly_leave`; `lateness` and
  `overtime` now require `attendance`.

### Phase 3: advances, loans, incentives, penalties, pay items given

- **Advances** (`apps/loans/advances.py`): within a month's pay; recovered by that month's payroll.
  **Loans** (`apps/loans/services.py`): equal installments (remainder on the last), one loan at a
  time, postponing moves the rest a month on, cancelling only before the first payment.
- **Incentives and penalties** (`apps/adjustments`): one catalogue of types with a kind; four
  amount methods as strategies (`domain/amounts.py`: fixed, % of salary, days, hours); each entry
  keeps the amount worked out on its day. Each kind has its own permissions.
- **Pay items given** (`apps/compensation`, `PayItemAssignment`): an item for an employee from a
  date (to a date or open), once or every pay period, month or week; no two of the same item
  over the same days.
- **Shared**: "who it's for" (one employee, a department, a branch) in `apps/employees/targets.py`
  with one form partial and `static/core/js/reveal.js`; entries given together share a batch; `EmployeeRowsViewSet` for every API over employees' rows;
  `apps/core/months.py`; `MonthField`; `apps/core/migration_helpers.for_each_tenant`.
- Features: `advances`, `loans`, `incentives`, `penalties`; `pay_items` now also covers giving them.

### Phase 4: payroll

The rules are in [docs/payroll-design.md](docs/payroll-design.md).

- **Pay terms** (`apps/employees`): how pay is counted (fixed salary, daily or hourly wage) is
  separate from how often it is paid (monthly, every two weeks, weekly).
- **Calendars and periods** (`apps/payroll`): one pay calendar per frequency (monthly from a
  start day; weekly and biweekly from an anchor date); regular periods come from it, off-cycle
  periods have any dates and a reason.
- **Runs**: draft → approved → paid, or reversed (approved, not paid). A run is for everyone, a
  branch or a department; employees already in a run of the same days are skipped and listed.
  Manual lines on a draft's payslips survive recalculation.
- **The engine** (`domain/engine.py`): a pipeline of calculators, each tied to its feature;
  `gather.py` reads attendance, pay items (allocated to the period by `domain/allocation.py`),
  incentives, penalties, advances, installments, insurance and tax. Issues are blocking (stop
  approval) or warnings.
- **Approval** freezes each payslip (lines, issues and a snapshot of its inputs) and records
  what it paid (`PaidSource`, unique while not released), so nothing is paid twice;
  installments become paid and advances recovered. A reversal releases them.
- **Locks** (`apps/core/locks.py`): the other apps refuse changes to days and sources an
  approved run covers (`PAYROLL_LOCKED`).
- Pages: payroll runs, a run, a payslip, pay calendars. Payroll has its own permissions
  (`payroll.run.*`, `payroll.calendar.manage`); no feature switches it off.

### After phase 4: history, bulk changes, batches

From "PayRole — the four gaps" (decisions of 2026-10-29).

- **History pages** read the payroll tables: `apps/audit/catalog.py` finds the audited tables
  from their triggers, `labels.py` names them by model (a test checks every audited model and
  column has a name), and `{% history_link record %}` takes the table from the model. A record's
  history includes its parts (rows deleted with it: an employee's pay and hours, a loan's
  installments, a batch's rows). An unknown table now shows nothing (it showed everything).
- **Bulk changes with a preview** (`apps/core/bulk.py`, `static/core/js/bulk.js`,
  `layouts/bulk_form.html`): each employee's row runs the same service as a single entry inside
  a savepoint; the preview is the save, rolled back. Saving keeps every row, or (when asked) the
  ones that pass; a second submission fails on the first one's rows. Groups:
  `employees.targets.Group` (chosen employees, a department, a branch).
  - Hourly leave for a group, one or more spans a day (`attendance/hourly.py`); several
    non-overlapping hourly leaves a day are allowed now.
  - Attendance by hand for a group, the same times or each their own, with a reason
    (`attendance/entries.py`); judged like clock times.
  - Working hours for a group from a date, for good or until a last day
    (`employees/group_hours.py`); earlier days and approved payroll are never rewritten.
- **Incentive and penalty batches** (`AdjustmentBatch`): draft (edited freely, never paid) →
  approved; reopened or cancelled with a reason while unpaid; once paid, a correction batch pays
  or takes back the difference in a later payroll. `adjustments.<kind>.approve` is a new
  permission. Every change bumps the batch's revision with its reason.

### Phase 5: reports, PDF and Excel

- **Reports** (`apps/reports`): a registry (`registry.py`) of reports, each a class with
  filters (dates, month, year, branch, department, employee, choices) and a `run()` that
  returns tables; a report reads with the permission of the screen its data comes from, so the
  same members see it, in the same branches, and a feature switched off hides its reports.
  Reports live in `catalog/`: payroll register and totals by run (read from the frozen
  payslips), attendance day by day and totals, leave balances, leave and hourly leave taken,
  advances, loans and what is left, installments, incentives, penalties, pay items given, the
  employee list (pay only for those allowed to see it).
- **Export** (`exporters.py`, Template Method): one walk over the tables, written as PDF (the
  A4 sheet, sideways when wide, page numbers) or Excel (real numbers and dates, formats,
  right-to-left in Arabic). Exporting is the `reports.export` permission and the
  `reports_export` feature; reading and printing on screen are not.
- **PDF** (`apps/printing/pdf.py`, from Saas_ERP): headless Chromium in a small thread pool;
  the page loads only our static and media files, with no scripts and no network. Without
  Chromium, a page says to use Print → Save as PDF (503).
- **Payslips** (`apps/payroll/printing.py`): one payslip or a whole run as a PDF, one per page,
  from the frozen lines; a draft run says "Draft" across the page.

### Phase 6: devices, the mobile app, WhatsApp

- **Fingerprint devices** (`apps/devices`): ZKTeco ADMS ("push"), as PayRole spoke it
  (`protocol.py`: pure parsing and answers; `iclock.py`: `/iclock/cdata`, `/getrequest`,
  `/devicecmd` on the client's own address, no CSRF). A device is known by its serial (unique
  across every client); what it sends is kept as sent, and a PIN linked to an employee becomes
  attendance punches (not on days an approved payroll covers). Commands (test, pull users, pull
  punches) go one at a time and expire. Feature `zk_devices` (off by default).
- **The mobile app** (`apps/mobile`, contract in [docs/mobile-api.md](docs/mobile-api.md)):
  `/api/v1/` answers exactly as PayRole's did (paths, shapes, Arabic messages, status codes),
  on this system's records: punches are attendance punches (source "mobile") on the employee's
  work day (night shifts work); leave is a leave request. SimpleJWT tokens carry the client
  (`tid`) and are refused on another client's host. The fingerprint proof (HMAC, one phone per
  employee, nonces), GPS tracking and the geofence (branch location and radius) are features.
  An employee gets a login from their page (the built-in "Employee (app)" role), or a QR that
  signs the app in with no address and no password (`apps/mobile/qr.py`: a one-time code, of
  which only the hash is kept, for the minutes set on the company page). Each phone has a record
  (`apps/mobile/devices.py`), and signing one out takes effect at once.
- **Notifications** (`apps/notifications`): what an employee or a decider is told (leave asked
  for and decided, hourly leave, incentives, penalties, advances, loans, pay paid), in PayRole's
  words; the app polls them.
- **WhatsApp** (`apps/messaging`, gateway in `ops/wa-gateway`): payslips from the client's own
  number, linked by QR; one job per payslip, spaced out and retried, the PDF made when sent,
  never twice; every message logged with its result. Feature `whatsapp`. Without a gateway
  (development, tests) messages stay in memory (`WHATSAPP_CONSOLE`) until the service is
  switched on in the console.

### Phase 7: evaluations, the dashboard, the bell

- **Evaluations** (`apps/evaluations`, PayRole Eva): an employee, a year, the day, up to four
  notes, and a card as a PDF with their dates and, for readers allowed to see pay, the year's
  pay (the pay at the year's end × 12, and the pay items of the year's approved payslips).
  Feature `evaluations`.
- **The dashboard** (`apps/reports/dashboard.py`, PayRole Main Home): employees working, present
  today, the last approved net pay; present each day (14 days), net pay by department, net pay
  and overtime hours each month (12 months), new hires each month (24 months); what is waiting.
  Each block only for those allowed to see it. Charts are drawn on the server
  (`apps/core/charts.py`, `components/column_chart.html`, `bar_chart.html`): one validated
  series colour per mode, thin rounded marks, a tooltip on hover (`static/core/js/bars.js`),
  the same numbers as a table.
- **The bell** (`components/bell.html`, `static/core/js/bell.js`, from Saas_ERP): unread
  notifications and what needs attention (`apps/notifications/attention.py`: leave and hourly
  leave to decide, incentives and penalties to approve, payroll runs to approve, devices not
  calling), refreshed every minute; the notifications page.

### Phase 8: the platform console

On the platform host (`PLATFORM_HOSTS`, `admin.localhost` in development), for platform staff
only (`apps/platform/console`, `templates/console`, from Saas_ERP without its gold-market,
server and document-design pages):

- **Overview:** active clients, office users and app logins, employees working,
  payslips approved in 30 days, changes saved per day by all clients, the clients that need a
  look (idle, never used, suspended). Each client's figures are read inside its own
  tenant_context (`console/metrics.py`).
- **Clients:** sign a client up in one step (company, address `<slug>.<TENANT_BASE_DOMAIN>`,
  language, country, currency, time zone, owner, plan, trial, limits, contact); its page:
  plan, limits (the one in effect: the client's, else the plan's), company settings, extra
  domains, owners,
  features (own choice or the plan's, with what a feature still needs), status (active,
  suspended, archived) and its activity.
- **Limits:** branches, office users and employees' app logins, each its own limit (a plan's,
  or the client's own). An app login is a member holding only the "Employee (app)" role; it
  never takes an office user's place (`apps/platform/tenants/limits.py`). Adding, reactivating
  or changing the roles of a member checks the limit of their kind.
- **Custom domains** open as soon as they are added: `HostCheckMiddleware` answers the fixed
  hosts (`DJANGO_ALLOWED_HOSTS`), the platform hosts and every client's domains, and refuses any
  other host (400), so Django's `ALLOWED_HOSTS` is `"*"`. The web server gets each domain's
  HTTPS certificate on its first visit; it asks `https://<platform host>/tls/allowed/?domain=…`
  first (200 only for client and platform domains). With Caddy:
  `{ on_demand_tls { ask https://admin.example.com/tls/allowed/ } }` and a site block
  `https:// { tls { on_demand } reverse_proxy 127.0.0.1:8000 }`. The client points the domain
  at the server (DNS) before it is added.
- **WhatsApp** is run from the console (`console/whatsapp.py`, `tenants.WhatsAppService`), not
  from `.env`: on or off, the address, the key (made for you, encrypted, never shown), whether
  the gateway answers, and each client's number and messages this month. `manage.py
  run_wa_gateway` (started by `ops/dev.py`; one service in production) keeps the gateway in line
  with those settings: it starts, stops and restarts it on its own. The only step outside the
  console is installing it once: `npm ci` in `ops/wa-gateway`.
- **Suspension** stops the workspace, the mobile app and the fingerprint devices at once
  (403); background jobs skip the client; the data is kept.
- **Plans** (prices, limits, trial days, features), **Features** (which plan includes what, and
  how many clients use it), **Traffic** (requests, server time, refusals, limits, live),
  **Jobs** (worker, failures, run again, cancel), **Settings** (the platform's name, logos,
  sidebar links), **Activity** (everything staff did, `PlatformEvent`).
- The Django admin stays at `/django-admin/` for emergencies; `manage.py create_tenant` still
  works from the shell.

### Real-time search and the pickers

- **Search and filters** answer as you type (`static/core/js/live_filter.js`): any
  `<form method="get" data-live-filter>` fetches its own page and swaps everything around the
  form, so results, totals, tabs and pager stay right through the normal view and its
  permissions, the cursor stays where it is, and the address follows. A test refuses a GET form
  without it. The Ctrl+K palette and the dropdowns already searched as you type.
- **Date, month and time pickers** (`static/core/js/pickers.js`) replace every
  `<input type="date|month|time">` by themselves, also in rows added later. The real input stays
  in the form, hidden, and keeps sending ISO values, so nothing on the server changed. A date can
  be typed (`5/3/2026`, Arabic digits too), and one shared panel serves the whole page.

### Live notifications

The bell updates the moment something happens (`apps/notifications`):

- **Domain events** (`apps/core/events.py`, Observer): a service publishes what happened
  (`publish(LeaveRequested(...))`) and knows nothing about notifications; `handlers.py` subscribes
  and says who is told. A new notification is a new handler, no service changes.
- **`realtime.py`**: `announce` is a PostgreSQL NOTIFY, sent only when the transaction commits, so
  no extra service is needed and a rolled-back action announces nothing. It carries ids, never
  text. `Hub` is each process's one LISTEN connection, ringing the streams of that member.
- **`stream.py`**: Server-Sent Events at `/notifications/stream/`. It reads through the tenant's
  row-level security, ends every 30 minutes so the browser signs in again, and picks up from
  `Last-Event-ID`.
- **`static/core/js/live.js`**: only the tab in view holds a stream; it reconnects by itself, and
  falls back on asking every minute where streaming isn't possible.

Streaming needs an async server. In development `runserver` is one (daphne). In production:
`gunicorn config.asgi:application -k uvicorn_worker.UvicornWorker`. On a plain WSGI server the
stream answers 503 and the bell polls. Behind nginx, turn buffering off for that path (the
response already says `X-Accel-Buffering: no`).

## Setting up a development machine

Requirements: Python 3.13, PostgreSQL 15 or later, Node.js 22 or later.

1. **Python packages**

   ```powershell
   python -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements\dev.txt
   .\venv\Scripts\python.exe -m playwright install chromium   # server-side PDFs
   ```

2. **Database roles and database** (once, as the PostgreSQL superuser). Choose three passwords:

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d postgres `
     -f ops\db\bootstrap.sql -v dbname=payroll `
     -v owner_pw=OWNER_PASSWORD -v rw_pw=RW_PASSWORD -v platform_pw=PLATFORM_PASSWORD
   ```

   This creates `payroll_owner` (owns the tables, runs migrations and tests), `payroll_rw` (what
   the application connects as; it cannot bypass row-level security) and `payroll_platform`.

3. **`.env`**: copy `.env.example` to `.env` and put the passwords in `DATABASE_URL`
   (`payroll_rw`) and `DATABASE_OWNER_URL` (`payroll_owner`).

4. **Tables**

   ```powershell
   .\venv\Scripts\python.exe manage.py migrate --database owner
   ```

   On a development machine, `ops\db\setup_dev.ps1` does steps 2 and 3's database part in one go
   with the passwords already in `.env` (it asks for the `postgres` password only).

5. **A platform admin and a first client**

   ```powershell
   .\venv\Scripts\python.exe manage.py createsuperuser --database owner
   .\venv\Scripts\python.exe manage.py create_tenant --slug demo --name "Demo Co" --owner-username admin --owner-email admin@demo.test
   ```

   Or, for development, `manage.py create_demo`: a platform admin, two clients (`demo`,
   `acme`) and an owner, a branch-scoped manager and a viewer, all with the password
   `Demo-Pass-2026`.

6. **Run it**

   ```powershell
   .\venv\Scripts\python.exe ops\dev.py
   ```

   This starts everything in one terminal: the web server, the background worker, the CSS
   watcher and the WhatsApp gateway's supervisor (it runs the gateway once it is switched on in
   the console). Ctrl+C stops them all. Add `--migrate`
   to apply new migrations first, or `--port 8001` for another port.

   - The client's workspace: http://demo.localhost:8000/ (sign in as `owner`).
   - The platform console: http://admin.localhost:8000/ (sign in as `admin@platform.test`).

## Frontend assets

```powershell
npm install
npm run build        # fonts, Tom Select, icons, then the CSS
npm run watch:css    # while editing templates
```

The built files (`static/core/css/app.css`, `apps/core/ui_icons.json`, `static/vendor/`) are
committed; CI fails if they are stale. A new icon name goes in `assets/copy-assets.mjs`.

## Checks

```powershell
.\venv\Scripts\python.exe ops\check.py           # lint, translations, migrations, tests
.\venv\Scripts\python.exe ops\check.py --quick   # without the tests
.\venv\Scripts\python.exe ops\i18n\messages.py extract   # new strings into the Arabic catalogue
.\venv\Scripts\python.exe ops\i18n\messages.py compile
```
