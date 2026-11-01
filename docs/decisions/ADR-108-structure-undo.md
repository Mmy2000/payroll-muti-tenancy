# ADR-108: Undo and redo on the company structure page

**Status:** Accepted · 2026-11-01

## Context

The company structure page reorganises real records: dated assignments, and the branches a
department operates in. People expect undo on a workspace like this. Moving someone back is not an
undo: it adds a row to their history, cannot bring back a row a same-day move replaced, and cannot
tell a mistake being corrected from a real transfer. Payroll reads these rows, so an undo must also
respect approved periods and never overwrite what happened since.

## Decision

- Each change on this page is a `StructureChange` holding the before and after of every assignment
  row and placement it touched. Undo puts the before back and redo the after, by one mechanism.
- This is the one place assignment rows are deleted or put back rather than added to. It is allowed
  because such a row is the same member's own recent change, being withdrawn, and only while nothing
  else has happened to it. `EffectiveDatedModel`'s rule still holds for everything else. The audit
  triggers record the withdrawal like any other change.
- A step only runs if the records still equal the side it starts from. If they don't, if a later
  move exists, or if an approved payroll covers those days, nothing changes: the step is dropped,
  since it can never become true again, and the member is told why.
- A member undoes only their own changes, with the permissions they hold at that moment. The last
  30 are kept, and a new change ends what could be redone.
- Arranging cards is not a record and stays in the browser. The two run in one order, so undo always
  takes back the last thing done.

## Consequences

- Moves made elsewhere, such as the employee page, are not on this stack, but they do stop a change
  they touched from being undone.
- A change someone else's work depends on cannot be undone. That is the point, but the person has to
  make the correction by hand.
- `StructureChange.details` keeps names as they were, so a label stays readable after a rename.
