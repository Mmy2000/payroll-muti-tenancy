"""What changes with the calendar alone: a last working day passing."""

from datetime import time

from django.utils.translation import gettext_lazy as _

from apps.platform.jobs.registry import daily, task


@task("employees.close_leavers_logins", label=_("Close the logins of employees who left"))
def close_leavers_logins():
    from .services.employees import close_leavers_logins

    close_leavers_logins()


daily("employees.close_leavers_logins", at=time(0, 30))
