"""Yearly evaluations (PayRole `Eva.Pev`, screens GHV11/GHV11a): an employee, a year, the day it
was written, and up to four notes. PayRole numbered them per branch; here per client."""

from __future__ import annotations

from django.db import models

from apps.core.models import TenantScopedModel


class Evaluation(TenantScopedModel):
    number = models.PositiveIntegerField()
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT,
                                 related_name="evaluations")
    year = models.PositiveSmallIntegerField()
    evaluated_on = models.DateField()
    note_1 = models.TextField(blank=True)
    note_2 = models.TextField(blank=True)
    note_3 = models.TextField(blank=True)
    note_4 = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "-number"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"],
                                               name="evaluations_number_uniq")]
        indexes = [models.Index(fields=["tenant", "employee", "year"],
                                name="evaluations_emp_year_idx")]

    def __str__(self):
        return f"#{self.number} {self.year}"

    @property
    def notes(self) -> list[str]:
        return [n for n in (self.note_1, self.note_2, self.note_3, self.note_4) if n]
