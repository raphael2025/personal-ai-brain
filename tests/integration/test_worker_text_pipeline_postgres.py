"""End-to-end PostgreSQL test for authorized text extraction workers."""

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

from personal_ai_brain.evaluation.postgres_search import PostgresLexicalSearchRepository  # noqa: E402
from personal_ai_brain.ingestion.artifacts import PostgresArtifactRepository  # noqa: E402
from personal_ai_brain.ingestion.models import JobSpec  # noqa: E402
from personal_ai_brain.ingestion.repository import PostgresJobRepository  # noqa: E402
from personal_ai_brain.workers.handlers import (  # noqa: E402
    TextExtractionHandler,
    text_extraction_config_digest,
)
from personal_ai_brain.workers.runtime import WorkerRuntime  # noqa: E402
from personal_ai_brain.workers.source_access import (  # noqa: E402
    AuthorizedSourceReader,
    PostgresWorkerSourceAccessRepository,
    WorkerMountMap,
)

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0002_durable_jobs.sql",
    Path(__file__).parents[2]
    / "infrastructure/postgres/migrations/0003_fenced_artifact_publication.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0004_worker_root_grants.sql",
]


def test_worker_extracts_only_authorized_source_and_persists_artifact(tmp_path: Path):
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_worker_pipeline_test_{uuid4().hex}"
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

        root_id, asset_id, version_id, location_id = (
            uuid4(), uuid4(), uuid4(), uuid4()
        )
        worker_id = str(uuid4())
        root_path = tmp_path / "root"
        root_path.mkdir()
        source_content = b"# Project notes\nThis is a local-only test fixture.\n"
        (root_path / "notes.md").write_bytes(source_content)
        source_digest = hashlib.sha256(source_content).hexdigest()

        connection.execute(
            """
            INSERT INTO storage_roots (id, display_name, uri, kind)
            VALUES (%s, 'Pipeline test', 'file:///tmp/pipeline-test', 'local')
            """,
            (root_id,),
        )
        connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
        connection.execute(
            """
            INSERT INTO asset_versions (id, asset_id, sha256, size_bytes, detected_mime_type)
            VALUES (%s, %s, %s, %s, 'text/markdown')
            """,
            (version_id, asset_id, source_digest, len(source_content)),
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

        jobs = PostgresJobRepository(connect)
        source_access = PostgresWorkerSourceAccessRepository(connect)
        artifacts = PostgresArtifactRepository(connect)
        jobs.register_worker(worker_id, "pipeline worker", ("text",))
        source_access.grant_root(worker_id, str(root_id), actor="integration-test")

        config_digest = text_extraction_config_digest()
        job_id = jobs.enqueue(
            JobSpec(
                asset_version_id=str(version_id),
                task_type="extract_text",
                semantic_version="1.0.0",
                config_digest=config_digest,
                idempotency_key=f"pipeline:{uuid4()}",
                payload={"root_id": str(root_id), "relative_path": "../../ignored"},
                required_capabilities=("text",),
            )
        )
        reader = AuthorizedSourceReader(
            source_access, WorkerMountMap(worker_id, {str(root_id): root_path})
        )
        handler = TextExtractionHandler(reader, artifacts)
        runtime = WorkerRuntime(
            jobs, worker_id, {"extract_text": handler}, lease_seconds=60
        )

        assert runtime.run_once() is True
        assert runtime.run_once() is False

        job = connection.execute(
            "SELECT status FROM processing_jobs WHERE id = %s", (job_id,)
        ).fetchone()
        assert job[0] == "succeeded"
        artifact = connection.execute(
            """
            SELECT source_sha256, config_digest, job_id, lease_generation,
                   published_by_worker_id, payload, content_sha256, size_bytes, status
              FROM processing_artifacts
            """
        ).fetchone()
        assert artifact is not None
        assert artifact[0] == source_digest
        assert artifact[1] == config_digest
        assert str(artifact[2]) == job_id
        assert artifact[3] == 1
        assert str(artifact[4]) == worker_id
        assert artifact[5]["text"] == source_content.decode("utf-8")
        assert artifact[6] == hashlib.sha256(source_content).hexdigest()
        assert artifact[7] == len(source_content)
        assert artifact[8] == "ready"

        search = PostgresLexicalSearchRepository(connect)
        results = search.search(
            "local-only test fixture",
            root_id=str(root_id),
            document_type="md",
        )
        assert len(results) == 1
        assert results[0].asset_id == str(asset_id)
        assert results[0].asset_version_id == str(version_id)
        assert results[0].relative_path == "notes.md"
        assert results[0].source_sha256 == source_digest
        assert "local-only" in results[0].snippet
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )
