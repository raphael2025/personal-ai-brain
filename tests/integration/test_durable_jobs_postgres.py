"""PostgreSQL integration tests for durable job leases and fencing."""

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

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0002_durable_jobs.sql",
]


@pytest.fixture
def db():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_jobs_test_{uuid4().hex}"
    try:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
        )
        for migration in MIGRATIONS:
            connection.execute(migration.read_text(encoding="utf-8"))
        yield connection
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def seed_source(db):
    root_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    db.execute(
        """
        INSERT INTO storage_roots (id, display_name, uri, kind)
        VALUES (%s, 'Job fixture', 'file:///tmp/job-fixture', 'local')
        """,
        (root_id,),
    )
    db.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
    db.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 8)
        """,
        (version_id, asset_id, "f" * 64),
    )
    return version_id


def enqueue(db, version_id, *, key=None, max_attempts=3, required=("text",)):
    job_id = uuid4()
    key = key or f"test:{uuid4()}"
    returned = db.execute(
        """
        SELECT enqueue_processing_job(
            %s, %s, 'extract_text', '1.0.0', %s, %s,
            %s::jsonb, %s, 10, %s
        )
        """,
        (
            job_id,
            version_id,
            "a" * 64,
            key,
            '{"mode":"plain"}',
            list(required),
            max_attempts,
        ),
    ).fetchone()[0]
    return returned, key


def register_worker(db, *, capabilities=("text",)):
    worker_id = uuid4()
    db.execute(
        """
        INSERT INTO workers (id, display_name, capabilities)
        VALUES (%s, 'Test worker', %s)
        """,
        (worker_id, list(capabilities)),
    )
    return worker_id


def claim(db, worker_id, lease_seconds=60):
    return db.execute(
        "SELECT * FROM claim_processing_job(%s, %s)",
        (worker_id, lease_seconds),
    ).fetchone()


def test_enqueue_is_idempotent_and_rejects_spec_conflicts(db):
    version_id = seed_source(db)
    first_id, key = enqueue(db, version_id)
    second_id, _ = enqueue(db, version_id, key=key)

    assert first_id == second_id
    assert db.execute(
        "SELECT count(*) FROM processing_jobs WHERE idempotency_key = %s", (key,)
    ).fetchone()[0] == 1

    with pytest.raises(psycopg.Error, match="different job specification"):
        with db.transaction():
            db.execute(
                """
                SELECT enqueue_processing_job(
                    %s, %s, 'other_task', '1.0.0', %s, %s,
                    '{}'::jsonb, ARRAY['text'], 10, 3
                )
                """,
                (uuid4(), version_id, "a" * 64, key),
            )


def test_worker_claims_only_compatible_jobs_and_completes_with_fence(db):
    version_id = seed_source(db)
    job_id, _ = enqueue(db, version_id, required=("text", "pdf"))
    incompatible = register_worker(db, capabilities=("text",))
    compatible = register_worker(db, capabilities=("text", "pdf"))

    assert claim(db, incompatible) is None
    lease = claim(db, compatible)
    assert lease[0] == job_id
    assert lease[6] == 1
    assert lease[7] == 1

    db.execute(
        "SELECT heartbeat_processing_job(%s, %s, %s, 60)",
        (job_id, compatible, lease[7]),
    )
    db.execute(
        "SELECT complete_processing_job(%s, %s, %s)",
        (job_id, compatible, lease[7]),
    )

    assert db.execute(
        "SELECT status, lease_owner_worker_id, lease_expires_at FROM processing_jobs WHERE id = %s",
        (job_id,),
    ).fetchone() == ("succeeded", None, None)
    assert db.execute(
        "SELECT status FROM job_attempts WHERE job_id = %s", (job_id,)
    ).fetchone()[0] == "succeeded"


def test_expired_lease_is_reclaimed_and_stale_worker_is_fenced(db):
    version_id = seed_source(db)
    job_id, _ = enqueue(db, version_id)
    first_worker = register_worker(db)
    second_worker = register_worker(db)

    first = claim(db, first_worker)
    db.execute(
        """
        UPDATE processing_jobs SET lease_expires_at = now() - interval '1 second'
         WHERE id = %s
        """,
        (job_id,),
    )
    db.execute(
        """
        UPDATE job_attempts SET lease_expires_at = now() - interval '1 second'
         WHERE job_id = %s AND lease_generation = %s
        """,
        (job_id, first[7]),
    )

    second = claim(db, second_worker)
    assert second[0] == job_id
    assert second[6] == 2
    assert second[7] == 2
    assert db.execute(
        "SELECT status FROM job_attempts WHERE job_id = %s ORDER BY attempt_no",
        (job_id,),
    ).fetchall() == [("abandoned",), ("running",)]

    with pytest.raises(psycopg.Error, match="LEASE_LOST"):
        with db.transaction():
            db.execute(
                "SELECT complete_processing_job(%s, %s, %s)",
                (job_id, first_worker, first[7]),
            )

    db.execute(
        "SELECT complete_processing_job(%s, %s, %s)",
        (job_id, second_worker, second[7]),
    )


def test_retryable_failure_uses_bounded_retry_wait(db):
    version_id = seed_source(db)
    job_id, _ = enqueue(db, version_id, max_attempts=2)
    worker_id = register_worker(db)
    first = claim(db, worker_id)

    status = db.execute(
        "SELECT fail_processing_job(%s, %s, %s, %s, true)",
        (job_id, worker_id, first[7], "temporary failure"),
    ).fetchone()[0]
    assert status == "retry_wait"
    assert claim(db, worker_id) is None

    db.execute(
        "UPDATE processing_jobs SET available_at = now() WHERE id = %s", (job_id,)
    )
    second = claim(db, worker_id)
    assert second[6] == 2

    status = db.execute(
        "SELECT fail_processing_job(%s, %s, %s, %s, true)",
        (job_id, worker_id, second[7], "second failure"),
    ).fetchone()[0]
    assert status == "failed"
    assert db.execute(
        "SELECT status, attempt_count FROM processing_jobs WHERE id = %s",
        (job_id,),
    ).fetchone() == ("failed", 2)


def test_cancel_queued_and_active_jobs(db):
    version_id = seed_source(db)
    queued_job, _ = enqueue(db, version_id)
    assert db.execute(
        "SELECT request_processing_job_cancel(%s)", (queued_job,)
    ).fetchone()[0] == "cancelled"

    active_job, _ = enqueue(db, version_id)
    worker_id = register_worker(db)
    lease = claim(db, worker_id)
    assert lease[0] == active_job
    assert db.execute(
        "SELECT request_processing_job_cancel(%s)", (active_job,)
    ).fetchone()[0] == "cancel_requested"
    db.execute(
        "SELECT acknowledge_processing_job_cancel(%s, %s, %s)",
        (active_job, worker_id, lease[7]),
    )
    assert db.execute(
        "SELECT status FROM processing_jobs WHERE id = %s", (active_job,)
    ).fetchone()[0] == "cancelled"
