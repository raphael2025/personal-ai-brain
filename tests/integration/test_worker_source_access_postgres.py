"""PostgreSQL integration tests for root-scoped worker source access."""

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

from personal_ai_brain.ingestion.models import JobSpec  # noqa: E402
from personal_ai_brain.ingestion.repository import PostgresJobRepository  # noqa: E402
from personal_ai_brain.workers.source_access import (  # noqa: E402
    AuthorizedSourceReader,
    PostgresWorkerSourceAccessRepository,
    SourceAccessDeniedError,
    SourceContentMismatchError,
    WorkerMountMap,
)

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0002_durable_jobs.sql",
    Path(__file__).parents[2]
    / "infrastructure/postgres/migrations/0003_fenced_artifact_publication.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0004_worker_root_grants.sql",
]


@pytest.fixture
def source_environment(tmp_path: Path):
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_source_access_test_{uuid4().hex}"
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

        repository = PostgresWorkerSourceAccessRepository(connect)
        jobs = PostgresJobRepository(connect)
        root_id, asset_id, version_id, location_id = (
            uuid4(), uuid4(), uuid4(), uuid4()
        )
        worker_id = str(uuid4())
        root = tmp_path / "root"
        root.mkdir()
        source = root / "notes.md"
        content = b"# Private source\n"
        source.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()

        connection.execute(
            """
            INSERT INTO storage_roots (id, display_name, uri, kind)
            VALUES (%s, 'Source test', 'file:///tmp/source-test', 'local')
            """,
            (root_id,),
        )
        connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
        connection.execute(
            """
            INSERT INTO asset_versions (id, asset_id, sha256, size_bytes, detected_mime_type)
            VALUES (%s, %s, %s, %s, 'text/markdown')
            """,
            (version_id, asset_id, digest, len(content)),
        )
        connection.execute(
            """
            INSERT INTO asset_locations (
                id, asset_id, storage_root_id, current_version_id,
                relative_path, normalized_path_key, path_normalizer_version
            )
            VALUES (%s, %s, %s, %s, 'notes.md', 'notes.md', 'v1-exact')
            """,
            (location_id, asset_id, root_id, version_id),
        )
        connection.commit()
        jobs.register_worker(worker_id, "source test worker", ("text",))
        yield (
            repository,
            jobs,
            connection,
            str(root_id),
            str(version_id),
            worker_id,
            root,
            content,
            digest,
        )
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def make_lease(jobs, worker_id: str, version_id: str, root_id: str):
    job_id = jobs.enqueue(
        JobSpec(
            asset_version_id=version_id,
            task_type="extract_text",
            semantic_version="1.0.0",
            config_digest="c" * 64,
            idempotency_key=f"source-test:{uuid4()}",
            payload={"root_id": root_id, "relative_path": "../../etc/passwd"},
            required_capabilities=("text",),
        )
    )
    lease = jobs.claim(worker_id)
    assert lease is not None and lease.job_id == job_id
    return lease


def test_worker_reads_only_granted_root_and_ignores_payload_path(source_environment):
    (
        repository, jobs, _, root_id, version_id, worker_id,
        root, content, digest,
    ) = source_environment
    repository.grant_root(worker_id, root_id, actor="operator")
    mounts = WorkerMountMap(worker_id, {root_id: root})
    reader = AuthorizedSourceReader(repository, mounts)

    result = reader.read_for_lease(make_lease(jobs, worker_id, version_id, root_id))

    assert result.content == content
    assert result.reference.relative_path == "notes.md"
    assert result.reference.sha256 == digest
    assert (root / "notes.md").read_bytes() == content


def test_worker_without_grant_cannot_resolve_source(source_environment):
    repository, jobs, _, root_id, version_id, worker_id, root, _, _ = source_environment
    reader = AuthorizedSourceReader(
        repository, WorkerMountMap(worker_id, {root_id: root})
    )

    with pytest.raises(SourceAccessDeniedError):
        reader.read_for_lease(make_lease(jobs, worker_id, version_id, root_id))


def test_revoked_grant_blocks_the_next_source_read(source_environment):
    repository, jobs, _, root_id, version_id, worker_id, root, _, _ = source_environment
    repository.grant_root(worker_id, root_id, actor="operator")
    assert repository.revoke_root(worker_id, root_id, actor="operator") is True
    reader = AuthorizedSourceReader(
        repository, WorkerMountMap(worker_id, {root_id: root})
    )

    with pytest.raises(SourceAccessDeniedError):
        reader.read_for_lease(make_lease(jobs, worker_id, version_id, root_id))


def test_symlink_source_is_rejected_even_with_root_grant(source_environment, tmp_path):
    (
        repository, jobs, connection, root_id, version_id, worker_id,
        root, _, _,
    ) = source_environment
    repository.grant_root(worker_id, root_id, actor="operator")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (root / "linked.md").symlink_to(outside)
    connection.execute(
        "UPDATE asset_locations SET relative_path = 'linked.md' WHERE current_version_id = %s",
        (version_id,),
    )
    connection.commit()
    reader = AuthorizedSourceReader(
        repository, WorkerMountMap(worker_id, {root_id: root})
    )

    with pytest.raises(OSError):
        reader.read_for_lease(make_lease(jobs, worker_id, version_id, root_id))


def test_source_bytes_must_match_registered_version(source_environment):
    (
        repository, jobs, _, root_id, version_id, worker_id,
        root, _, _,
    ) = source_environment
    repository.grant_root(worker_id, root_id, actor="operator")
    original_size = len((root / "notes.md").read_bytes())
    (root / "notes.md").write_bytes(b"X" * original_size)
    reader = AuthorizedSourceReader(
        repository, WorkerMountMap(worker_id, {root_id: root})
    )

    with pytest.raises(SourceContentMismatchError):
        reader.read_for_lease(make_lease(jobs, worker_id, version_id, root_id))


def test_reclaimed_lease_cannot_read_even_when_worker_has_root_grant(source_environment):
    (
        repository, jobs, connection, root_id, version_id, worker_id,
        root, _, _,
    ) = source_environment
    repository.grant_root(worker_id, root_id, actor="operator")
    old_lease = make_lease(jobs, worker_id, version_id, root_id)
    worker_b = str(uuid4())
    jobs.register_worker(worker_b, "replacement worker", ("text",))
    connection.execute(
        "UPDATE processing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (old_lease.job_id,),
    )
    connection.execute(
        "UPDATE job_attempts SET lease_expires_at = now() - interval '1 second' WHERE job_id = %s",
        (old_lease.job_id,),
    )
    connection.commit()

    replacement = jobs.claim(worker_b)
    assert replacement is not None
    assert replacement.job_id == old_lease.job_id
    reader = AuthorizedSourceReader(
        repository, WorkerMountMap(worker_id, {root_id: root})
    )

    with pytest.raises(SourceAccessDeniedError):
        reader.read_for_lease(old_lease)
