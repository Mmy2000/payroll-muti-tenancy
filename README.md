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
  Platform staff use the Django admin on the platform host until the console (phase 8).
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

## Setting up a development machine

Requirements: Python 3.13, PostgreSQL 15 or later, Node.js 22 or later.

1. **Python packages**

   ```powershell
   python -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements\dev.txt
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
   .\venv\Scripts\python.exe manage.py runserver
   ```

   - The client's workspace: http://demo.localhost:8000/ (sign in as `admin`).
   - The platform admin: http://admin.localhost:8000/ (clients, plans, features).
   - Background jobs: `.\venv\Scripts\python.exe manage.py run_worker`.

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
