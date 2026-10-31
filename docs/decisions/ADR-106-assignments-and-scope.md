# ADR-106: Dated assignments, company-wide permissions, and leaving ends access

**Status:** Accepted · 2026-11-01

## Context

An audit of the HR structure found that branch, department and job title had no history: a
transfer overwrote the card, so past days read the new branch, and a past paid holiday became an
unpaid absence. A person could not be hired twice. `Actor.can(code)` with no branch meant both
"in any branch" and "this isn't about branches", so a member limited to one branch could manage
users and widen their own scope. An employee leaving did nothing to their login.

## Decision

- **`EmployeeAssignment`** holds where an employee works and as what, by date, like `Compensation`
  and `WorkSchedule`. The card keeps the row in effect today, so everything that asks about now is
  unchanged, and anything about a past day reads that day's row. A change on the card holds from
  today; a dated change goes through `change_assignment`, which respects approved payroll.
- **`Payslip.branch` and `department`** record where the employee was at the end of the period.
- **`Position`** is a catalog of jobs. `job_title` stays as the text shown, so the mobile API,
  reports and imports don't change. Job titles in use became positions; a human may merge variants.
- **A person who returns keeps their record.** `rehire` closes the last period on the assignment
  row (`ended_on`, `leave_reason`), and the card starts over.
- **`company_wide` permissions** (users, roles, company settings, positions, the History, sign-ins)
  count only when held in every branch. `org.branch.manage` stays per branch: a member edits the
  branches it covers, and a new branch or a new head office needs it in every branch. A grant is checked against the branches the actor
  holds it in, and an Owner must cover every branch.
- **Leaving suspends the login** the day after the last working day, by service and by a daily job.
  A client's last Owner keeps theirs, or nobody could get in to put it right.

## Alternatives

- **A branch-scoped user manager**, seeing only their branch's users. Refused for now: a login can
  span branches, and the rule would need to say whose user that is.
- **A separate `EmploymentPeriod` table.** Not needed: periods can be read from the assignments, so
  there is one history instead of two.
- **Departments across branches.** Kept per branch, as in PayRole. A company-wide group can be added
  later without touching existing rows.

## Consequences

- Members whose role gave company-wide permissions for some branches only lose them: this is the
  fix, and such a role should be given for every branch or split.
- History before this change comes from the audit trail, so it goes back only as far as that does.
- Access follows the employee's current branch. After a transfer the old branch loses sight of their
  earlier records. This is unchanged, and would need a rule of its own.
- A payroll run for a past period of an employee who has since returned isn't supported: `hired_on`
  is the start of the current period.
