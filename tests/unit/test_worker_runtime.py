"""Unit tests for the pull-based worker runtime."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event
from time import sleep

from personal_ai_brain.ingestion.models import JobLease, LeaseLostError, PermanentJobError
from personal_ai_brain.workers.runtime import WorkerRuntime


class FakeRepository:
    def __init__(self, lease: JobLease) -> None:
        self.lease = lease
        self.completed = 0
        self.failures: list[tuple[str, bool]] = []
        self.heartbeats = 0
        self.lose_heartbeat = False
        self.claimed = False

    def register_worker(self, worker_id, display_name, capabilities):
        raise NotImplementedError

    def enqueue(self, job):
        raise NotImplementedError

    def claim(self, worker_id, *, lease_seconds=60):
        if self.claimed:
            return None
        self.claimed = True
        return self.lease

    def heartbeat(self, lease, *, lease_seconds=60):
        self.heartbeats += 1
        if self.lose_heartbeat:
            raise LeaseLostError("lease reclaimed")

    def complete(self, lease):
        self.completed += 1

    def fail(self, lease, error, *, retryable=True):
        self.failures.append((error, retryable))
        return "failed"

    def request_cancel(self, job_id):
        raise NotImplementedError

    def acknowledge_cancel(self, lease):
        raise NotImplementedError


def make_lease() -> JobLease:
    return JobLease(
        job_id="00000000-0000-0000-0000-000000000001",
        worker_id="00000000-0000-0000-0000-000000000002",
        asset_version_id="00000000-0000-0000-0000-000000000003",
        task_type="extract_text",
        semantic_version="1.0.0",
        config_digest="a" * 64,
        payload={"format": "text"},
        attempt_no=1,
        generation=1,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )


def test_runtime_completes_successful_handler():
    repository = FakeRepository(make_lease())
    runtime = WorkerRuntime(
        repository, repository.lease.worker_id, {"extract_text": lambda lease: None}
    )

    assert runtime.run_once() is True
    assert repository.completed == 1
    assert repository.failures == []


def test_runtime_marks_missing_handler_as_permanent_failure():
    repository = FakeRepository(make_lease())
    runtime = WorkerRuntime(repository, repository.lease.worker_id, {})

    assert runtime.run_once() is True
    assert repository.completed == 0
    assert repository.failures == [("NoHandlerRegistered", False)]


def test_runtime_retries_unexpected_handler_error_but_not_permanent_error():
    cases = (
        (ValueError("bad input"), True),
        (PermanentJobError("unsupported"), False),
    )
    for error, retryable in cases:
        repository = FakeRepository(make_lease())

        def handler(_lease, raised=error):
            raise raised

        runtime = WorkerRuntime(
            repository, repository.lease.worker_id, {"extract_text": handler}
        )
        runtime.run_once()

        assert repository.completed == 0
        assert repository.failures == [(type(error).__name__, retryable)]


def test_runtime_discards_result_when_heartbeat_loses_lease():
    repository = FakeRepository(make_lease())
    repository.lose_heartbeat = True

    def slow_handler(_lease):
        sleep(0.05)

    runtime = WorkerRuntime(
        repository, repository.lease.worker_id, {"extract_text": slow_handler},
        lease_seconds=5,
    )
    runtime.heartbeat_interval = 0.01

    runtime.run_once()

    assert repository.heartbeats >= 1
    assert repository.completed == 0
    assert repository.failures == []


def test_run_forever_stops_after_current_job():
    repository = FakeRepository(make_lease())
    stop = Event()

    def handler(_lease):
        stop.set()

    runtime = WorkerRuntime(
        repository, repository.lease.worker_id, {"extract_text": handler}
    )
    runtime.run_forever(stop)

    assert repository.completed == 1
