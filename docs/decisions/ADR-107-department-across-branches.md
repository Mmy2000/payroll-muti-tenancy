# ADR-107: A department operates in several branches

**Status:** Accepted · 2026-11-01

## Context

A department belonged to one branch, as in PayRole (`Pfn.br1`). "Sales" in three branches was three
rows with three codes, and nothing could report on Sales across the company. The people who use the
system want one department, with each branch keeping its own employees.

## Decision

- `Department` has one code and one name for the client, and `DepartmentBranch` lists the branches
  it operates in. Its people in a branch are the employees of that branch and that department:
  an employee's branch already said so, so nothing about employees changes.
- **An employee's department must be in their branch.** A branch can't be taken off a department
  while employees work there in it.
- **A choice of department keeps its branch.** "Branch A, Sales" means Sales in branch A: for
  bulk changes, incentives and penalties, pay items and payroll runs. With no branch chosen it
  means the whole department. Batches and runs record the branch (`target_branch_id`,
  `scope_branch_id`), and a run for a department in one branch needs the permission in that branch.
- **A change to a department reaches all its branches,** so it takes the permission in all of them.
  A branch manager sees a department that includes their branch, and edits it only when they cover
  every branch it is in.
- Departments of the same name, ignoring case and outer spaces, were merged. Batches and runs kept
  the branch they meant, and a code two departments shared was renumbered.

## Alternatives

- **A shared "department group" above per-branch rows.** Refused: it keeps a code per branch, which
  is what this decision removes.
- **Active or inactive per branch.** Not built: `is_active` is the department's. Taking the branch
  off it does the same job.

## Consequences

- The merge can't be reversed by a migration: the merged rows are gone.
- Department codes are the client's, so an Excel import uses the same code for every branch.
- Reports by department add up the whole department across branches.
