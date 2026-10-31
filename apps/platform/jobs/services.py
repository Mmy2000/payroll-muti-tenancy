"""What staff do to a job from the console: run it again, or cancel it."""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.platform.tenants.services import record

from .models import Job, JobStatus
from .worker import retry


def retry_job(job: Job, *, actor) -> Job:
    retry(job)
    record(actor, "job.retried", job.tenant, job=f"{job.name} #{job.pk}")
    return job


def cancel_job(job: Job, *, actor) -> Job:
    job.status, job.finished_at = JobStatus.CANCELLED, timezone.now()
    job.last_error = _("Cancelled from the console.")
    job.save(update_fields=["status", "finished_at", "last_error"])
    record(actor, "job.cancelled", job.tenant, job=f"{job.name} #{job.pk}")
    return job
