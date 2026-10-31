"""What changes with the calendar alone: a last working day passing, an assignment's day
arriving."""

from datetime import time

from django.utils.translation import gettext_lazy as _

from apps.platform.jobs.registry import daily, task


@task("employees.daily_upkeep", label=_("Close leavers' logins and apply dated assignments"))
def daily_upkeep():
    from .services.employees import apply_due_assignments, close_leavers_logins

    close_leavers_logins()
    apply_due_assignments()


daily("employees.daily_upkeep", at=time(0, 30))
