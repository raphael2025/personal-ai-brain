"""Lease-fenced persistence for deterministic extraction artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

from personal_ai_brain.extractors.models import ExtractionArtifact
from personal_ai_brain.ingestion.models import JobLease, LeaseLostError


class ArtifactConflictError(RuntimeError):
    """The same artifact identity was published with different output."""


class PostgresArtifactRepository:
    """Publishes JSON artifacts only while the caller owns the current job lease.

    The processing_jobs row is locked for the entire transaction. A stale or
    expired worker cannot create a visible artifact row. Payloads are stored in
    PostgreSQL for this initial bounded-text implementation; external blob
    staging and garbage collection are a later storage adapter.
    """

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
    def _uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"{field_name} must be a UUID string") from exc

    @staticmethod
    def _digest(value: str, field_name: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        return value

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f"{field_name} must be a non-empty string of at most 200 characters")
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
            raise ValueError(f"{field_name} must not contain ASCII control characters")
        return value.strip()

    def publish(
        self,
        lease: JobLease,
        artifact: ExtractionArtifact,
        *,
        config_digest: str,
    ) -> str:
        """Insert or return an identical artifact while the lease remains active."""
        job_id = self._uuid(lease.job_id, "job_id")
        worker_id = self._uuid(lease.worker_id, "worker_id")
        asset_version_id = self._uuid(artifact.asset_version_id, "asset_version_id")
        if artifact.asset_version_id != lease.asset_version_id:
            raise ValueError("artifact asset version does not match the leased job")
        if type(lease.generation) is not int or lease.generation <= 0:
            raise ValueError("lease generation must be a positive integer")
        source_sha256 = self._digest(artifact.source_sha256, "source_sha256")
        content_sha256 = self._digest(artifact.content_sha256, "content_sha256")
        config_digest = self._digest(config_digest, "config_digest")
        artifact_type = self._required_text(artifact.artifact_type, "artifact_type")
        processor_name = self._required_text(artifact.extractor_name, "processor_name")
        processor_version = self._required_text(
            artifact.extractor_version, "processor_version"
        )
        output_schema_version = self._required_text(
            artifact.output_schema_version, "output_schema_version"
        )
        if type(artifact.size_bytes) is not int or artifact.size_bytes < 0:
            raise ValueError("artifact size_bytes must be a non-negative integer")
        if not isinstance(artifact.payload, dict):
            raise ValueError("artifact payload must be a JSON object")
        payload_json = json.dumps(
            artifact.payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        with self._connection() as connection:
            job = connection.execute(
                """
                SELECT asset_version_id, status, lease_owner_worker_id,
                       lease_generation, lease_expires_at, config_digest,
                       lease_expires_at > clock_timestamp()
                  FROM processing_jobs
                 WHERE id = %s
                 FOR UPDATE
                """,
                (job_id,),
            ).fetchone()
            if (
                job is None
                or job[0] != asset_version_id
                or job[1] not in {"leased", "running"}
                or job[2] != worker_id
                or job[3] != lease.generation
                or not job[6]
            ):
                raise LeaseLostError("worker lease is no longer current")

            if str(job[5]).strip() != config_digest:
                raise ValueError("artifact config digest does not match the leased job")

            source = connection.execute(
                "SELECT sha256 FROM asset_versions WHERE id = %s",
                (asset_version_id,),
            ).fetchone()
            if source is None or str(source[0]).strip() != source_sha256:
                raise ValueError("artifact source digest does not match the immutable asset version")

            inserted = connection.execute(
                """
                INSERT INTO processing_artifacts (
                    id, asset_version_id, artifact_type, processor_name,
                    processor_version, output_schema_version, source_sha256,
                    config_digest, job_id, lease_generation,
                    published_by_worker_id, payload, content_sha256,
                    size_bytes, status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s, 'ready'
                )
                ON CONFLICT (
                    asset_version_id, artifact_type, processor_name,
                    processor_version, output_schema_version, config_digest
                ) WHERE config_digest IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                (
                    uuid4(),
                    asset_version_id,
                    artifact_type,
                    processor_name,
                    processor_version,
                    output_schema_version,
                    source_sha256,
                    config_digest,
                    job_id,
                    lease.generation,
                    worker_id,
                    payload_json,
                    content_sha256,
                    artifact.size_bytes,
                ),
            ).fetchone()
            if inserted is not None:
                return str(inserted[0])

            existing = connection.execute(
                """
                SELECT id, source_sha256, content_sha256, size_bytes, payload
                  FROM processing_artifacts
                 WHERE asset_version_id = %s
                   AND artifact_type = %s
                   AND processor_name = %s
                   AND processor_version = %s
                   AND output_schema_version = %s
                   AND config_digest = %s
                """,
                (
                    asset_version_id,
                    artifact_type,
                    processor_name,
                    processor_version,
                    output_schema_version,
                    config_digest,
                ),
            ).fetchone()
            if existing is None:
                raise RuntimeError("artifact identity conflict could not be resolved")

            existing_payload = existing[4]
            if isinstance(existing_payload, str):
                existing_payload = json.loads(existing_payload)
            if (
                str(existing[1]).strip() != source_sha256
                or str(existing[2]).strip() != content_sha256
                or existing[3] != artifact.size_bytes
                or existing_payload != artifact.payload
            ):
                raise ArtifactConflictError(
                    "the same source/processor/config identity produced different output"
                )
            return str(existing[0])
