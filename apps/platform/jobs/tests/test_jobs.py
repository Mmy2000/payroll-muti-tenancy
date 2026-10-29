"""The job queue: the outbox, running in the client's context, retries, schedules, workers and
the console page."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone, translation

from apps.core.tenancy import tenant_context
from apps.platform.jobs import registry
from apps.platform.jobs.models import Job, JobStatus
from apps.platform.jobs.registry import JobFailed, enqueue, task
from apps.platform.jobs.worker import (
    Scheduler,
    claim,
    execute,
    release_stale,
    retry_delay,
    run_pending,
)

pytestmark = pytest.mark.django_db
SEEN: list = []
FLAKY = {"left": 0}
ERRORS: list = []


@task("test.note")
def note(text):
    from apps.org.models import TenantProfile

    SEEN.append((text, TenantProfile.objects.values_list("display_name", flat=True).first(),
                 translation.get_language(), str(timezone.get_current_timezone())))


@task("test.flaky", max_attempts=3, on_error=lambda payload, error, final: ERRORS.append(final))
def flaky():
    if FLAKY["left"] > 0:
        FLAKY["left"] -= 1
        raise RuntimeError("SMTP is down")


@task("test.hopeless")
def hopeless():
    raise JobFailed("The invoice was deleted.")


@task("test.platform", per_tenant=False)
def platform_note():
    SEEN.append(("platform", None, None, None))


@pytest.fixture(autouse=True)
def _reset():
    SEEN.clear()
    ERRORS.clear()
    FLAKY["left"] = 0
    yield


def _due(job):
    Job.objects.filter(pk=job.pk).update(run_at=timezone.now())


def test_a_job_is_part_of_the_work_that_asks_for_it(tenant_a):
    with tenant_context(tenant_a.id):
        enqueue("test.note", text="kept")
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                enqueue("test.note", text="rolled back")
                raise RuntimeError("the sale failed")
    assert list(Job.objects.values_list("payload", flat=True)) == [{"text": "kept"}]
    with pytest.raises(ValueError):
        enqueue("test.note", text="no tenant")  # a client task needs a client
    with pytest.raises(KeyError):
        enqueue("test.unknown")


def test_it_runs_in_the_clients_context_language_and_time_zone(tenant_a, tenant_b):
    from apps.org.models import TenantProfile

    with tenant_context(tenant_b.id):
        TenantProfile.objects.update(locale="en", timezone="Asia/Dubai", display_name="Bravo Gold")
    enqueue("test.note", tenant_id=tenant_a.id, text="a")
    enqueue("test.note", tenant_id=tenant_b.id, text="b")
    enqueue("test.platform")
    assert run_pending() == 3
    assert ("b", "Bravo Gold", "en", "Asia/Dubai") in SEEN
    assert next(s for s in SEEN if s[0] == "a")[2] == "ar"
    assert ("platform", None, None, None) in SEEN
    assert set(Job.objects.values_list("status", flat=True)) == {JobStatus.DONE}


def test_a_failure_is_retried_later_then_given_up(tenant_a):
    FLAKY["left"] = 1
    job = enqueue("test.flaky", tenant_id=tenant_a.id)
    run_pending()
    job.refresh_from_db()
    assert (job.status, job.attempts, ERRORS) == (JobStatus.QUEUED, 1, [False])
    assert "SMTP is down" in job.last_error and job.run_at > timezone.now()
    assert run_pending() == 0  # not due yet
    _due(job)
    run_pending()
    job.refresh_from_db()
    assert (job.status, job.attempts) == (JobStatus.DONE, 2)

    FLAKY["left"] = 5
    job = enqueue("test.flaky", tenant_id=tenant_a.id)
    for _attempt in range(3):
        _due(job)
        run_pending()
    job.refresh_from_db()
    assert (job.status, job.attempts) == (JobStatus.FAILED, 3)
    assert ERRORS[-1] is True
    assert [retry_delay(n).total_seconds() for n in (1, 2, 3)] == [30, 120, 480]


def test_a_client_task_cannot_skip_its_transaction():
    with pytest.raises(ValueError):
        task("test.client_not_atomic", atomic=False)(lambda: None)


def test_a_hopeless_job_fails_at_once_and_an_inactive_client_is_skipped(tenant_a, tenant_b):
    job = enqueue("test.hopeless", tenant_id=tenant_a.id)
    run_pending()
    job.refresh_from_db()
    assert (job.status, job.attempts) == (JobStatus.FAILED, 1)
    assert job.last_error == "JobFailed: The invoice was deleted."

    tenant_b.status = "suspended"
    tenant_b.save(update_fields=["status"])
    job = enqueue("test.note", tenant_id=tenant_b.id, text="nope")
    run_pending()
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED and SEEN == []


def test_the_same_dedupe_key_is_kept_once(tenant_a):
    assert enqueue("test.note", tenant_id=tenant_a.id, dedupe_key="2026-10-06", text="x")
    assert enqueue("test.note", tenant_id=tenant_a.id, dedupe_key="2026-10-06", text="x") is None
    assert enqueue("test.platform", dedupe_key="day") and enqueue("test.platform",
                                                                  dedupe_key="day") is None
    assert Job.objects.count() == 2


def test_a_job_left_running_goes_back_in_the_queue(tenant_a):
    job = enqueue("test.note", tenant_id=tenant_a.id, text="x")
    claimed = claim("dead-worker")
    assert claimed.pk == job.pk and claim("other") is None  # nothing else due
    assert release_stale() == 0
    assert release_stale(timezone.now() + timedelta(minutes=20)) == 1
    job.refresh_from_db()
    assert job.status == JobStatus.QUEUED and execute(claim("w2"))


def test_one_failed_pass_does_not_stop_the_worker(tenant_a, monkeypatch):
    """A database error in one pass is logged and the worker goes on: the job queued before
    still runs."""
    from django.db import OperationalError

    from apps.platform.jobs.management.commands import run_worker
    job = enqueue("test.note", tenant_id=tenant_a.id, text="after the error")
    failures = iter([OperationalError("server closed the connection unexpectedly")])

    def tick(self, now=None):
        error = next(failures, None)
        if error is not None:
            raise error
        return 0

    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:  # the queue is empty again: stop the loop here
            raise KeyboardInterrupt

    monkeypatch.setattr(run_worker.Scheduler, "tick", tick)
    monkeypatch.setattr(run_worker.time, "sleep", sleep)
    monkeypatch.setattr(run_worker.connection, "close", lambda: None)  # keep the test's
    call_command("run_worker")
    job.refresh_from_db()
    assert job.status == JobStatus.DONE and sleeps[0] == run_worker.ERROR_PAUSE


def test_daily_schedules_follow_each_clients_clock(tenant_a, tenant_b, monkeypatch):
    from apps.org.models import TenantProfile

    with tenant_context(tenant_b.id):
        TenantProfile.objects.update(timezone="Asia/Tokyo")  # six hours ahead of Cairo
    monkeypatch.setattr(registry, "SCHEDULES", [registry.Schedule("test.note", time(7, 30),
                                                                  time(13, 30))])
    cairo = ZoneInfo("Africa/Cairo")
    scheduler = Scheduler()

    def tick(hour, minute=0, day=6):
        return scheduler.tick(datetime(2026, 10, day, hour, minute, tzinfo=cairo))

    assert tick(1, 0) == 0  # 07:00 in Tokyo
    assert tick(1, 45) == 1  # 07:45 in Tokyo
    assert tick(7, 40) == 1  # 07:40 in Cairo
    assert tick(9, 0) == 0  # once a day each
    assert Scheduler().tick(datetime(2026, 10, 6, 9, 0, tzinfo=cairo)) == 0  # another worker
    assert tick(23, 0) == 0  # past "until" in Cairo, too early in Tokyo
    assert tick(2, 0, day=7) == 1 and tick(8, 0, day=7) == 1
    keys = set(Job.objects.values_list("tenant_id", "dedupe_key"))
    assert keys == {(tenant_a.id, "2026-10-06"), (tenant_b.id, "2026-10-06"),
                    (tenant_a.id, "2026-10-07"), (tenant_b.id, "2026-10-07")}


def test_run_worker_once(tenant_a, capsys, monkeypatch):
    monkeypatch.setattr(registry, "SCHEDULES", [])  # whatever the time of day
    enqueue("test.note", tenant_id=tenant_a.id, text="cli")
    call_command("run_worker", "--once")
    assert "ran 1" in capsys.readouterr().out and SEEN[0][0] == "cli"
