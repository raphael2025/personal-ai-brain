"""Small pull-based worker runtime with lease heartbeats and fencing."""

from __future__ import annotations

from collections.abc import Mapping
from threading import Event, Thread
from typing import Protocol

from personal_ai_brain.ingestion.models import (
    JobLease,
    LeaseLostError,
    PermanentJobError,
)
from personal_ai_brain.ingestion.repository import JobRepository


class JobHandler(Protocol):
    def __call__(self, lease: JobLease) -> None: ...


class WorkerRuntime:
    """Executes registered handlers without granting access to source paths.

    Handlers receive immutable source-version identity and a job payload. They
    must use separately authorized source/artifact adapters; this runtime does
    not provide arbitrary filesystem or network access.
    """

    def __init__(
        self,
        repository: JobRepository,
        worker_id: str,
        handlers: Mapping[str, JobHandler],
        *,
        lease_seconds: int = 60,
        poll_interval: float = 2.0,
    ) -> None:
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 86400:
            raise ValueError("lease_seconds must be between 5 and 86400")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.repository = repository
        self.worker_id = worker_id
        self.handlers = dict(handlers)
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.heartbeat_interval = max(1.0, lease_seconds / 3)

    def _heartbeat_loop(self, lease: JobLease, stop: Event, lost: Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            try:
                self.repository.heartbeat(lease, lease_seconds=self.lease_seconds)
            except Exception:
                # A failed heartbeat makes publication unsafe. Do not attempt a
                # completion/failure transition with a lease we cannot verify.
                lost.set()
                return

    def run_once(self) -> bool:
        """Claim and process one job. Return False when no compatible job exists."""
        lease = self.repository.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if lease is None:
            return False

        handler = self.handlers.get(lease.task_type)
        if handler is None:
            try:
                self.repository.fail(
                    lease, "NoHandlerRegistered", retryable=False
                )
            except LeaseLostError:
                pass
            return True

        stop_heartbeat = Event()
        lease_lost = Event()
        heartbeat = Thread(
            target=self._heartbeat_loop,
            args=(lease, stop_heartbeat, lease_lost),
            name=f"pab-heartbeat-{lease.job_id}",
            daemon=True,
        )
        heartbeat.start()

        failure: Exception | None = None
        try:
            handler(lease)
        except Exception as exc:
            failure = exc
        finally:
            stop_heartbeat.set()
            heartbeat.join()

        if lease_lost.is_set():
            return True

        try:
            if failure is None:
                self.repository.complete(lease)
            else:
                self.repository.fail(
                    lease,
                    type(failure).__name__,
                    retryable=not isinstance(failure, PermanentJobError),
                )
        except LeaseLostError:
            # Another worker reclaimed the lease; this worker must discard its
            # result and must not attempt any later state transition.
            return True
        return True

    def run_forever(self, stop_event: Event) -> None:
        """Poll until stop_event is set; active handlers finish before return."""
        while not stop_event.is_set():
            claimed = self.run_once()
            if not claimed:
                stop_event.wait(self.poll_interval)
