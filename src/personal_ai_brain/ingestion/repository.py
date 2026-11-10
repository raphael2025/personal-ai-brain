"""PostgreSQL adapter for the durable job and worker lease contract."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol
from uuid import UUID, uuid4

from personal_ai_brain.ingestion.models import JobLease, JobSpec, LeaseLostError


class JobRepository(Protocol):
    def register_worker(
        self, worker_id: str, display_name: str, capabilities: tuple[str, ...]
    ) -> None: ...

    def enqueue(self, job: JobSpec) -> str: ...

    def claim(self, worker_id: str, *, lease_seconds: int = 60) -> JobLease | None: ...

    def heartbeat(self, lease: JobLease, *, lease_seconds: int = 60) -> None: ...

    def complete(self, lease: JobLease) -> None: ...

    def fail(self, lease: JobLease, error: str, *, retryable: bool = True) -> str: ...

    def request_cancel(self, job_id: str) -> str: ...

    def acknowledge_cancel(self, lease: JobLease) -> None: ...


class PostgresJobRepository:
    """DB-API adapter; psycopg is loaded by the caller and remains optional."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        close_connections: bool = True,
    ) -> None:
        self._connect = connection_factory
        self._close_connections = close_connections

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection.transaction():
                yield connection
        finally:
            if self._close_connections:
                connection.close()

    @staticmethod
    def _uuid(value: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("job and worker IDs must be UUID strings") from exc

    @staticmethod
    def _lease_lost(exc: Exception) -> bool:
        return "LEASE_LOST" in str(exc)

    def register_worker(
        self, worker_id: str, display_name: str, capabilities: tuple[str, ...]
    ) -> None:
        worker_uuid = self._uuid(worker_id)
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("display_name must be non-empty")
        if len(display_name) > 200 or any(ord(c) < 0x20 or ord(c) == 0x7F for c in display_name):
            raise ValueError(
                "display_name must be at most 200 characters without control characters"
            )
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capabilities must not contain duplicates")
        if any(not isinstance(item, str) or not item.strip() for item in capabilities):
            raise ValueError("capabilities must contain non-empty strings")

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO workers (id, display_name, capabilities, enabled)
                VALUES (%s, %s, %s, true)
                ON CONFLICT (id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        capabilities = EXCLUDED.capabilities,
                        enabled = true,
                        updated_at = now()
                """,
                (worker_uuid, display_name.strip(), list(capabilities)),
            )

    def enqueue(self, job: JobSpec) -> str:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT enqueue_processing_job(
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
                )
                """,
                (
                    uuid4(),
                    self._uuid(job.asset_version_id),
                    job.task_type,
                    job.semantic_version,
                    job.config_digest,
                    job.idempotency_key,
                    json.dumps(job.payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
                    list(job.required_capabilities),
                    job.priority,
                    job.max_attempts,
                ),
            ).fetchone()
        return str(row[0])

    def claim(self, worker_id: str, *, lease_seconds: int = 60) -> JobLease | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM claim_processing_job(%s, %s)",
                (self._uuid(worker_id), lease_seconds),
            ).fetchone()
        if row is None:
            return None
        return JobLease(
            job_id=str(row[0]),
            worker_id=str(worker_id),
            asset_version_id=str(row[1]),
            task_type=row[2],
            semantic_version=row[3],
            config_digest=row[4],
            payload=row[5],
            attempt_no=row[6],
            generation=row[7],
            expires_at=row[8],
        )

    def heartbeat(self, lease: JobLease, *, lease_seconds: int = 60) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    "SELECT heartbeat_processing_job(%s, %s, %s, %s)",
                    (
                        self._uuid(lease.job_id),
                        self._uuid_from_lease_worker(lease),
                        lease.generation,
                        lease_seconds,
                    ),
                )
        except Exception as exc:
            if self._lease_lost(exc):
                raise LeaseLostError("worker lease is no longer current") from exc
            raise

    @staticmethod
    def _uuid_from_lease_worker(lease: JobLease) -> UUID:
        return UUID(str(lease.worker_id))

    def complete(self, lease: JobLease) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    "SELECT complete_processing_job(%s, %s, %s)",
                    (
                        self._uuid(lease.job_id),
                        self._uuid_from_lease_worker(lease),
                        lease.generation,
                    ),
                )
        except Exception as exc:
            if self._lease_lost(exc):
                raise LeaseLostError("worker lease is no longer current") from exc
            raise

    def fail(self, lease: JobLease, error: str, *, retryable: bool = True) -> str:
        safe_error = error.strip() if isinstance(error, str) else "unspecified worker failure"
        safe_error = safe_error[:1000] or "unspecified worker failure"
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT fail_processing_job(%s, %s, %s, %s, %s)",
                    (
                        self._uuid(lease.job_id),
                        self._uuid_from_lease_worker(lease),
                        lease.generation,
                        safe_error,
                        retryable,
                    ),
                ).fetchone()
        except Exception as exc:
            if self._lease_lost(exc):
                raise LeaseLostError("worker lease is no longer current") from exc
            raise
        return str(row[0])

    def request_cancel(self, job_id: str) -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT request_processing_job_cancel(%s)",
                (self._uuid(job_id),),
            ).fetchone()
        return str(row[0])

    def acknowledge_cancel(self, lease: JobLease) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    "SELECT acknowledge_processing_job_cancel(%s, %s, %s)",
                    (
                        self._uuid(lease.job_id),
                        self._uuid_from_lease_worker(lease),
                        lease.generation,
                    ),
                )
        except Exception as exc:
            if self._lease_lost(exc):
                raise LeaseLostError("worker lease is no longer current") from exc
            raise
