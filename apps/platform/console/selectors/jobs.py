"""The job queue as the console reads it: what is waiting, what failed, which workers are up."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Count, Q, QuerySet

from apps.platform.jobs.models import Job, JobStatus, Worker


def job_counts(now: datetime) -> dict[str, int]:
    day = now - timedelta(hours=24)
    return Job.objects.aggregate(
        due=Count("id", filter=Q(status=JobStatus.QUEUED, run_at__lte=now, attempts=0)),
        retrying=Count("id", filter=Q(status=JobStatus.QUEUED, attempts__gt=0)),
        later=Count("id", filter=Q(status=JobStatus.QUEUED, run_at__gt=now, attempts=0)),
        running=Count("id", filter=Q(status=JobStatus.RUNNING)),
        done=Count("id", filter=Q(status=JobStatus.DONE, finished_at__gte=day)),
        failed=Count("id", filter=Q(status=JobStatus.FAILED, finished_at__gte=day)),
    )


def oldest_due(now: datetime) -> datetime | None:
    return (Job.objects.filter(status=JobStatus.QUEUED, run_at__lte=now)
            .order_by("run_at").values_list("run_at", flat=True).first())


def latest_workers() -> list[Worker]:
    return list(Worker.objects.order_by("-seen_at"))


def jobs_in_view(view: str) -> QuerySet[Job]:
    """Newest first. `view` is problems, waiting, done, or anything else for all."""
    queryset = Job.objects.select_related("tenant")
    if view == "problems":
        queryset = queryset.filter(Q(status=JobStatus.FAILED)
                                   | Q(status=JobStatus.QUEUED, attempts__gt=0))
    elif view == "waiting":
        queryset = queryset.filter(status__in=(JobStatus.QUEUED, JobStatus.RUNNING))
    elif view == "done":
        queryset = queryset.filter(status__in=(JobStatus.DONE, JobStatus.CANCELLED))
    return queryset.order_by("-created_at", "-id")


def find_job(pk: int) -> Job | None:
    return Job.objects.select_related("tenant").filter(pk=pk).first()
