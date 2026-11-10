"""Integration tests for the Python PostgreSQL job repository adapter."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("PERSONAL_AI_BRAIN_TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("PostgreSQL test database URL is not configured", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402

from personal_ai_brain.ingestion.models import JobSpec, LeaseLostError  # noqa: E402
from personal_ai_brain.ingestion.repository import PostgresJobRepository  # noqa: E402

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0002_durable_jobs.sql",
]


@pytest.fixture
def setup_registry():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_job_repo_test_{uuid4().hex}"
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
        repository = PostgresJobRepository(
            lambda: psycopg.connect(
                DATABASE_URL, options=f"-c search_path={schema_name}"
            )
        )
        root_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
        connection.execute(
            """
            INSERT INTO storage_roots (id, display_name, uri, kind)
            VALUES (%s, 'Adapter test', 'file:///tmp/job-adapter', 'local')
            """,
            (root_id,),
        )
        connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
        connection.execute(
            """
            INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
            VALUES (%s, %s, %s, 4)
            """,
            (version_id, asset_id, "b" * 64),
        )
        connection.commit()
        yield repository, connection, str(version_id)
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def make_spec(version_id: str, *, key: str | None = None) -> JobSpec:
    return JobSpec(
        asset_version_id=version_id,
        task_type="extract_text",
        semantic_version="1.0.0",
        config_digest="c" * 64,
        idempotency_key=key or f"extract:{uuid4()}",
        payload={"encoding": "utf-8"},
        required_capabilities=("text",),
        max_attempts=2,
    )


def test_repository_register_enqueue_claim_heartbeat_and_complete(setup_registry):
    repository, connection, version_id = setup_registry
    worker_id = str(uuid4())
    repository.register_worker(worker_id, "adapter worker", ("text",))
    job_id = repository.enqueue(make_spec(version_id))

    lease = repository.claim(worker_id, lease_seconds=60)
    assert lease is not None
    assert lease.job_id == job_id
    assert lease.worker_id == worker_id
    assert lease.payload == {"encoding": "utf-8"}

    repository.heartbeat(lease, lease_seconds=60)
    repository.complete(lease)

    assert connection.execute(
        "SELECT status FROM processing_jobs WHERE id = %s", (job_id,)
    ).fetchone()[0] == "succeeded"


def test_repository_fail_and_cancel_paths(setup_registry):
    repository, connection, version_id = setup_registry
    worker_id = str(uuid4())
    repository.register_worker(worker_id, "adapter worker", ("text",))

    retry_job = repository.enqueue(make_spec(version_id))
    lease = repository.claim(worker_id)
    assert lease is not None and lease.job_id == retry_job
    assert repository.fail(lease, "TemporaryFailure", retryable=True) == "retry_wait"

    cancel_job = repository.enqueue(make_spec(version_id))
    assert repository.request_cancel(cancel_job) == "cancelled"
    assert connection.execute(
        "SELECT status FROM processing_jobs WHERE id = %s", (cancel_job,)
    ).fetchone()[0] == "cancelled"


def test_repository_rejects_stale_lease(setup_registry):
    repository, connection, version_id = setup_registry
    worker_a, worker_b = str(uuid4()), str(uuid4())
    repository.register_worker(worker_a, "worker A", ("text",))
    repository.register_worker(worker_b, "worker B", ("text",))
    job_id = repository.enqueue(make_spec(version_id))

    old_lease = repository.claim(worker_a)
    assert old_lease is not None
    connection.execute(
        "UPDATE processing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (job_id,),
    )
    connection.execute(
        "UPDATE job_attempts SET lease_expires_at = now() - interval '1 second' WHERE job_id = %s",
        (job_id,),
    )
    connection.commit()

    new_lease = repository.claim(worker_b)
    assert new_lease is not None and new_lease.generation > old_lease.generation

    with pytest.raises(LeaseLostError):
        repository.complete(old_lease)
    repository.complete(new_lease)
