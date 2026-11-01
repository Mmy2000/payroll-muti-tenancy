"""Console → Jobs: is a worker running, what is waiting, what failed (and run it again)."""

from datetime import timedelta

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.paging import paginate
from apps.platform.jobs.models import Job, JobStatus
from apps.platform.jobs.registry import TASKS
from apps.platform.jobs.services import cancel_job, retry_job

from ..selectors.jobs import find_job, job_counts, jobs_in_view, latest_workers, oldest_due
from ..selectors.settings import settings_row
from .common import staff_required

ALIVE_WITHIN = timedelta(seconds=60)  # workers heartbeat every 15 s between jobs
VIEWS = ("problems", "waiting", "done", "all")


@staff_required
def jobs(request):
    now = timezone.now()
    counts = job_counts(now)
    oldest = oldest_due(now)
    workers = latest_workers()
    alive = [w for w in workers if now - w.seen_at <= ALIVE_WITHIN]

    view = request.GET.get("view", "problems")
    view = view if view in VIEWS else "problems"
    page = paginate(request, jobs_in_view(view), settings_row().page_size)
    rows = [{"job": job, "label": TASKS[job.name].label if job.name in TASKS else job.name}
            for job in page.object_list]
    return render(request, "console/jobs.html", {
        "section": "jobs", "counts": counts, "oldest": oldest, "workers": workers,
        "alive": alive, "now": now, "view": view, "page": page, "rows": rows,
    })


def _job(pk) -> Job:
    job = find_job(pk)
    if job is None:
        raise Http404
    return job


def _back(request):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}):
        return redirect(target)
    return redirect("console-jobs")


@staff_required
@require_POST
def job_retry(request, pk):
    job = _job(pk)
    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.QUEUED):
        messages.error(request, _("Only a waiting, failed or cancelled job can be run again."))
    else:
        retry_job(job, actor=request.user)
        messages.success(request, _("The job will run again in a moment."))
    return _back(request)


@staff_required
@require_POST
def job_cancel(request, pk):
    job = _job(pk)
    if job.status != JobStatus.QUEUED:
        messages.error(request, _("Only a waiting job can be cancelled."))
    else:
        cancel_job(job, actor=request.user)
        messages.success(request, _("Job cancelled."))
    return _back(request)
