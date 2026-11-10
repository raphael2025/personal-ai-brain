"""PostgreSQL tests for lease-fenced artifact publication."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("PERSONAL_AI_BRAIN_TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("PostgreSQL test database URL is not configured", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402

from personal_ai_brain.extractors.models import ExtractionArtifact  # noqa: E402
from personal_ai_brain.ingestion.artifacts import (  # noqa: E402
    ArtifactConflictError,
    PostgresArtifactRepository,
)
from personal_ai_brain.ingestion.models import JobSpec, LeaseLostError  # noqa: E402
from personal_ai_brain.ingestion.repository import PostgresJobRepository  # noqa: E402

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0002_durable_jobs.sql",
    Path(__file__).parents[2]
    / "infrastructure/postgres/migrations/0003_fenced_artifact_publication.sql",
]


@pytest.fixture
def artifact_environment():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_artifact_test_{uuid4().hex}"
    try:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
        )
        for migration in MIGRATIONS:
            connection.execute(migration.read_text(encoding="utf-8"))
        connection.commit()

        def connect():
            return psycopg.connect(
                DATABASE_URL, options=f"-c search_path={schema_name}"
            )

        jobs = PostgresJobRepository(connect)
        artifacts = PostgresArtifactRepository(connect)
        root_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
        source_digest = "b" * 64
        connection.execute(
            """
            INSERT INTO storage_roots (id, display_name, uri, kind)
            VALUES (%s, 'Artifact test', 'file:///tmp/artifact-test', 'local')
            """,
            (root_id,),
        )
        connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
        connection.execute(
            """
            INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
            VALUES (%s, %s, %s, 12)
            """,
            (version_id, asset_id, source_digest),
        )
        connection.commit()
        yield jobs, artifacts, connection, str(version_id), source_digest
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def enqueue_and_claim(jobs, version_id: str, worker_id: str, *, key: str):
    jobs.register_worker(worker_id, "artifact test worker", ("text",))
    job_id = jobs.enqueue(
        JobSpec(
            asset_version_id=version_id,
            task_type="extract_text",
            semantic_version="1.0.0",
            config_digest="c" * 64,
            idempotency_key=key,
            payload={},
            required_capabilities=("text",),
        )
    )
    lease = jobs.claim(worker_id)
    assert lease is not None and lease.job_id == job_id
    return lease


def make_artifact(version_id: str, source_digest: str, text: str = "extracted"):
    encoded = text.encode("utf-8")
    return ExtractionArtifact(
        asset_version_id=version_id,
        source_sha256=source_digest,
        extractor_name="text-markdown",
        extractor_version="1.0.0",
        output_schema_version="1",
        artifact_type="extracted_text",
        payload={"text": text},
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
    )


def test_publish_persists_provenance_and_is_idempotent_across_jobs(artifact_environment):
    jobs, artifacts, connection, version_id, source_digest = artifact_environment
    worker_a, worker_b = str(uuid4()), str(uuid4())
    first_lease = enqueue_and_claim(jobs, version_id, worker_a, key="first")
    artifact = make_artifact(version_id, source_digest)

    first_id = artifacts.publish(first_lease, artifact, config_digest="c" * 64)
    jobs.complete(first_lease)

    second_lease = enqueue_and_claim(jobs, version_id, worker_b, key="second")
    second_id = artifacts.publish(second_lease, artifact, config_digest="c" * 64)

    assert first_id == second_id
    row = connection.execute(
        """
        SELECT asset_version_id, artifact_type, processor_name, processor_version,
               output_schema_version, source_sha256, config_digest, job_id,
               lease_generation, published_by_worker_id, payload, content_sha256,
               size_bytes, status
          FROM processing_artifacts WHERE id = %s
        """,
        (first_id,),
    ).fetchone()
    assert str(row[0]) == version_id
    assert row[5] == source_digest
    assert row[6] == "c" * 64
    assert row[7] == jobs._uuid(first_lease.job_id)
    assert row[8] == first_lease.generation
    assert row[9] == jobs._uuid(worker_a)
    assert row[10] == {"text": "extracted"}
    assert row[12] == len("extracted")
    assert row[13] == "ready"


def test_stale_worker_cannot_publish_after_lease_reclaim(artifact_environment):
    jobs, artifacts, connection, version_id, source_digest = artifact_environment
    worker_a, worker_b = str(uuid4()), str(uuid4())
    old_lease = enqueue_and_claim(jobs, version_id, worker_a, key="reclaim")
    jobs.register_worker(worker_b, "artifact test worker B", ("text",))
    connection.execute(
        "UPDATE processing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (old_lease.job_id,),
    )
    connection.execute(
        "UPDATE job_attempts SET lease_expires_at = now() - interval '1 second' WHERE job_id = %s",
        (old_lease.job_id,),
    )
    connection.commit()

    new_lease = jobs.claim(worker_b)
    assert new_lease is not None and new_lease.generation > old_lease.generation
    with pytest.raises(LeaseLostError):
        artifacts.publish(
            old_lease,
            make_artifact(version_id, source_digest),
            config_digest="c" * 64,
        )

    assert connection.execute("SELECT count(*) FROM processing_artifacts").fetchone()[0] == 0
    new_id = artifacts.publish(
        new_lease,
        make_artifact(version_id, source_digest),
        config_digest="c" * 64,
    )
    assert new_id


def test_same_artifact_identity_with_different_output_is_rejected(artifact_environment):
    jobs, artifacts, _, version_id, source_digest = artifact_environment
    worker_a, worker_b = str(uuid4()), str(uuid4())
    first_lease = enqueue_and_claim(jobs, version_id, worker_a, key="conflict-a")
    artifacts.publish(
        first_lease,
        make_artifact(version_id, source_digest, "first"),
        config_digest="c" * 64,
    )
    jobs.complete(first_lease)

    second_lease = enqueue_and_claim(jobs, version_id, worker_b, key="conflict-b")
    with pytest.raises(ArtifactConflictError):
        artifacts.publish(
            second_lease,
            make_artifact(version_id, source_digest, "different"),
            config_digest="c" * 64,
        )


def test_source_digest_must_match_immutable_asset_version(artifact_environment):
    jobs, artifacts, _, version_id, source_digest = artifact_environment
    lease = enqueue_and_claim(jobs, version_id, str(uuid4()), key="wrong-source")
    with pytest.raises(ValueError, match="source digest"):
        artifacts.publish(lease, make_artifact(version_id, "a" * 64), config_digest="c" * 64)


def test_artifact_config_must_match_job_config(artifact_environment):
    jobs, artifacts, _, version_id, source_digest = artifact_environment
    lease = enqueue_and_claim(jobs, version_id, str(uuid4()), key="wrong-config")
    with pytest.raises(ValueError, match="config digest"):
        artifacts.publish(lease, make_artifact(version_id, source_digest), config_digest="d" * 64)
