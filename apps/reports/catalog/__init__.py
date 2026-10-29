"""Every report, by section. Importing this package registers them (apps/reports/permissions.py
does, when the permission catalog is built)."""

from . import attendance, pay, payroll, people  # noqa: F401
