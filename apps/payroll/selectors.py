"""What a member may see of payroll: runs of their scope, and the labels of what is in them."""

from __future__ import annotations

from django.db.models import Q

from .domain.engine import ISSUES, LINE_LABELS
from .models import PayrollRun, ScopeKind
from .services import READ


def visible_runs(actor):
    """Every run for a member reading payroll in all branches; otherwise the runs of their
    branches (a run for everyone or a department spans branches they can't see)."""
    runs = PayrollRun.objects.select_related("period")
    branches = actor.branch_ids(READ) if actor is not None else None
    if branches is None:
        return runs
    return runs.filter(Q(scope=ScopeKind.BRANCH) & Q(scope_id__in=branches))


def line_label(line) -> str:
    """"Incentive · Good month" for a named line of a system kind; the name or the kind alone
    otherwise."""
    kind = LINE_LABELS.get(line.code)
    if kind and line.label:
        return f"{kind} · {line.label}"
    return line.label or str(kind or line.code)


def issue_text(issue: dict) -> str:
    message = ISSUES.get(issue.get("code"))
    if message is None:
        return issue.get("code", "")
    try:
        return str(message) % issue.get("params", {})
    except (KeyError, TypeError, ValueError):
        return str(message)
