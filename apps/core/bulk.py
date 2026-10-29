"""Bulk changes with a preview: one change for many employees (hourly leave, working hours,
manual attendance), checked row by row, shown before anything is kept, then saved.

The preview *is* the save, rolled back: every row runs the same service function a single
entry uses (its permissions, locks, policies and checks) inside a savepoint, and at the end the
transaction is undone. So what the preview shows is exactly what saving does, and nothing can
pass one and not the other. Saving runs the rows again, from scratch:

* if every row passes, all are kept;
* if some fail, nothing is kept unless the caller said to leave those out (`skip_failed`, the
  "save the ones that pass" button the preview offers); the failures are reported either way.

Running the rows one after another in one transaction also catches clashes inside the request
itself (two intervals of the same employee that overlap), and a second submission of the same
change fails on the first one's rows instead of saving twice.

    items = [bulk.Item(employee, "10:00–11:00", partial(record_hourly_leave, ...))
             for employee in people]
    return bulk.run(items, save=save, skip_failed=skip_failed)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.translation import gettext as _

from .errors import AppError, DomainError

MAX_ROWS = 2000


def _messages(error: AppError) -> list[str]:
    """What went wrong with a row, in words: the field messages, or the error's own."""
    found = []
    for messages in error.fields.values():
        found += [str(m) for m in (messages if isinstance(messages, list) else [messages])
                  if str(m) not in found]
    return found or [error.message]


@dataclass(frozen=True)
class Item:
    """One row of work: who, what (in words, for the preview), the call that saves it, and
    what is worth knowing but doesn't stop it (asked just before saving, so it sees the rows
    before it)."""

    employee: object
    detail: str
    apply: Callable[[], object]
    warn: Callable[[], Iterable[str]] | None = None


@dataclass
class Row:
    employee_id: int
    name: str
    code: int | None
    detail: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"employee_id": self.employee_id, "name": self.name, "code": self.code,
                "detail": self.detail, "ok": self.ok, "errors": self.errors,
                "warnings": self.warnings}


@dataclass
class Outcome:
    rows: list[Row]
    saved: int  # rows kept (0 for a preview)

    @property
    def passed(self) -> int:
        return sum(1 for row in self.rows if row.ok)

    @property
    def failed(self) -> int:
        return len(self.rows) - self.passed

    def as_dict(self) -> dict:
        return {"rows": [row.as_dict() for row in self.rows], "passed": self.passed,
                "failed": self.failed, "saved": self.saved}


class BulkFailed(DomainError):
    """Saving was asked for, some rows fail and leaving them out wasn't: nothing was kept."""

    code = "BULK_ROWS_FAILED"

    def __init__(self, outcome: Outcome):
        super().__init__(_("%(count)s rows have problems; nothing was saved.")
                         % {"count": outcome.failed})
        self.outcome = outcome
        self.details = outcome.as_dict()


def run(items: Iterable[Item], *, save: bool, skip_failed: bool = False) -> Outcome:
    rows: list[Row] = []
    with transaction.atomic():
        for item in items:
            employee = item.employee
            row = Row(employee.pk, employee.name, getattr(employee, "code", None), item.detail)
            if len(rows) >= MAX_ROWS:
                raise DomainError(_("At most %(count)s rows at a time.") % {"count": MAX_ROWS},
                                  code="BULK_TOO_MANY")
            try:
                with transaction.atomic():
                    row.warnings = list(item.warn()) if item.warn else []
                    item.apply()
            except AppError as error:
                row.errors = _messages(error)
            rows.append(row)
        outcome = Outcome(rows, saved=0)
        keep = save and outcome.passed and (skip_failed or not outcome.failed)
        if keep:
            outcome.saved = outcome.passed
        else:
            transaction.set_rollback(True)
    if save and outcome.failed and not skip_failed:
        raise BulkFailed(outcome)
    return outcome
