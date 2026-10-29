"""Old notifications go: read ones after 90 days, unread ones after a year (PayRole kept 90)."""

from datetime import time

from django.utils.translation import gettext_lazy as _

from apps.platform.jobs.registry import daily, task


@task("notifications.clean_up", label=_("Clean up old notifications"))
def clean_up():
    from .services import clean_up

    clean_up()


daily("notifications.clean_up", at=time(4, 0))
