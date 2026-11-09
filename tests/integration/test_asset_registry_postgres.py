"""PostgreSQL integration tests for the initial Asset Registry migration."""

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

MIGRATION = (
    Path(__file__).parents[2]
    / "infrastructure"
    / "postgres"
    / "migrations"
    / "0001_asset_registry.sql"
)


@pytest.fixture
def db():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_test_{uuid4().hex}"
    try:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
        )
        connection.execute(MIGRATION.read_text(encoding="utf-8"))
        yield connection
    finally:
        connection.rollback()
        connection.close()


def seed_location(db, *, path: str = "docs/readme.md") -> dict[str, object]:
    root_id = uuid4()
    asset_id = uuid4()
    version_id = uuid4()
    location_id = uuid4()
    db.execute(
        """
        INSERT INTO storage_roots (id, display_name, uri, kind)
        VALUES (%s, 'Test root', 'file:///tmp/brain-test', 'local')
        """,
        (root_id,),
    )
    db.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
    db.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 4)
        """,
        (version_id, asset_id, "a" * 64),
    )
    db.execute(
        """
        INSERT INTO asset_locations (
            id, asset_id, storage_root_id, current_version_id,
            relative_path, normalized_path_key, path_normalizer_version
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'v1')
        """,
        (location_id, asset_id, root_id, version_id, path, path.casefold()),
    )
    return {
        "root_id": root_id,
        "asset_id": asset_id,
        "version_id": version_id,
        "location_id": location_id,
    }


def create_scan(db, root_id, *, status: str = "complete"):
    scan_id = uuid4()
    stored_status = "running" if status == "complete" else status
    finished = (
        "NULL"
        if stored_status in {"pending", "running"}
        else "now()"
    )
    db.execute(
        f"""
        INSERT INTO scan_runs (
            id, storage_root_id, status, scanner_version, finished_at
        )
        VALUES (%s, %s, %s, 'integration-test', {finished})
        """,
        (scan_id, root_id, stored_status),
    )
    return scan_id


def finish_scan(db, scan_id, *, status: str = "complete") -> None:
    db.execute(
        """
        UPDATE scan_runs
           SET status = %s, finished_at = now()
         WHERE id = %s AND status = 'running'
        """,
        (status, scan_id),
    )


def reconcile_complete_scan(db, scan_id):
    finish_scan(db, scan_id)
    return db.execute(
        "SELECT reconcile_missing_asset_locations(%s)", (scan_id,)
    ).fetchone()[0]


def add_observation(db, scan_id, path: str, *, excluded: bool = False):
    db.execute(
        """
        INSERT INTO scan_observations (
            id, scan_run_id, relative_path, normalized_path_key,
            path_normalizer_version, entry_kind, size_bytes, is_excluded
        )
        VALUES (%s, %s, %s, %s, 'v1', 'file', 4, %s)
        """,
        (uuid4(), scan_id, path, path.casefold(), excluded),
    )


def test_complete_scan_marks_unobserved_location_missing_and_logs_event(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])

    changed = reconcile_complete_scan(db, scan_id)
    state = db.execute(
        "SELECT availability FROM asset_locations WHERE id = %s",
        (seeded["location_id"],),
    ).fetchone()[0]
    event_count = db.execute(
        "SELECT count(*) FROM asset_location_events WHERE scan_run_id = %s",
        (scan_id,),
    ).fetchone()[0]

    assert changed == 1
    assert state == "missing"
    assert event_count == 1


@pytest.mark.parametrize("status", ["partial", "failed", "cancelled", "running"])
def test_incomplete_scan_cannot_mark_location_missing(db, status: str) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"], status=status)

    with pytest.raises(psycopg.Error):
        with db.transaction():
            if status == "running":
                db.execute(
                    "SELECT reconcile_missing_asset_locations(%s)", (scan_id,)
                )
            else:
                reconcile_complete_scan(db, scan_id)

    state = db.execute(
        "SELECT availability FROM asset_locations WHERE id = %s",
        (seeded["location_id"],),
    ).fetchone()[0]
    assert state == "available"


def test_complete_scan_refreshes_seen_and_excluded_locations(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])
    add_observation(db, scan_id, "docs/readme.md", excluded=True)
    finish_scan(db, scan_id)

    changed = db.execute(
        "SELECT reconcile_missing_asset_locations(%s)", (scan_id,)
    ).fetchone()[0]
    state = db.execute(
        "SELECT availability FROM asset_locations WHERE id = %s",
        (seeded["location_id"],),
    ).fetchone()[0]

    assert changed == 1
    assert state == "excluded"


def test_duplicate_observation_delivery_is_rejected(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])
    add_observation(db, scan_id, "docs/readme.md")

    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            add_observation(db, scan_id, "docs/readme.md")


def test_observations_are_immutable_after_scan_completion(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])

    finish_scan(db, scan_id)

    with pytest.raises(psycopg.errors.RaiseException):
        with db.transaction():
            add_observation(db, scan_id, "late.txt")


def test_terminal_scan_cannot_be_reopened(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])

    finish_scan(db, scan_id)

    with pytest.raises(psycopg.errors.RaiseException):
        with db.transaction():
            db.execute(
                "UPDATE scan_runs SET status = 'running', finished_at = NULL WHERE id = %s",
                (scan_id,),
            )


def test_content_change_adds_version_without_overwriting_history(db) -> None:
    seeded = seed_location(db)
    next_version_id = uuid4()
    db.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 5)
        """,
        (next_version_id, seeded["asset_id"], "b" * 64),
    )
    db.execute(
        "UPDATE asset_locations SET current_version_id = %s WHERE id = %s",
        (next_version_id, seeded["location_id"]),
    )

    versions = db.execute(
        "SELECT count(*) FROM asset_versions WHERE asset_id = %s",
        (seeded["asset_id"],),
    ).fetchone()[0]
    current_version = db.execute(
        "SELECT current_version_id FROM asset_locations WHERE id = %s",
        (seeded["location_id"],),
    ).fetchone()[0]

    assert versions == 2
    assert current_version == next_version_id


def test_rename_keeps_asset_identity_and_marks_old_path_missing(db) -> None:
    seeded = seed_location(db, path="old-name.md")
    new_location_id = uuid4()
    db.execute(
        """
        INSERT INTO asset_locations (
            id, asset_id, storage_root_id, current_version_id,
            relative_path, normalized_path_key, path_normalizer_version
        )
        VALUES (%s, %s, %s, %s, 'new-name.md', 'new-name.md', 'v1')
        """,
        (
            new_location_id,
            seeded["asset_id"],
            seeded["root_id"],
            seeded["version_id"],
        ),
    )
    scan_id = create_scan(db, seeded["root_id"])
    add_observation(db, scan_id, "new-name.md")
    finish_scan(db, scan_id)

    db.execute("SELECT reconcile_missing_asset_locations(%s)", (scan_id,))

    old_state = db.execute(
        "SELECT availability FROM asset_locations WHERE id = %s",
        (seeded["location_id"],),
    ).fetchone()[0]
    new_asset_id = db.execute(
        "SELECT asset_id FROM asset_locations WHERE id = %s",
        (new_location_id,),
    ).fetchone()[0]

    assert old_state == "missing"
    assert new_asset_id == seeded["asset_id"]



def test_reconciliation_is_idempotent(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])

    first = reconcile_complete_scan(db, scan_id)
    second = reconcile_complete_scan(db, scan_id)
    event_count = db.execute(
        "SELECT count(*) FROM asset_location_events WHERE scan_run_id = %s",
        (scan_id,),
    ).fetchone()[0]

    assert first == 1
    assert second == 0
    assert event_count == 1


def test_same_content_in_two_assets_is_not_automatically_merged(db) -> None:
    first_asset_id = uuid4()
    second_asset_id = uuid4()
    db.execute("INSERT INTO assets (id) VALUES (%s)", (first_asset_id,))
    db.execute("INSERT INTO assets (id) VALUES (%s)", (second_asset_id,))
    db.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 10), (%s, %s, %s, 10)
        """,
        (
            uuid4(),
            first_asset_id,
            "c" * 64,
            uuid4(),
            second_asset_id,
            "c" * 64,
        ),
    )

    count = db.execute(
        "SELECT count(*) FROM asset_versions WHERE sha256 = %s AND size_bytes = 10",
        ("c" * 64,),
    ).fetchone()[0]

    assert count == 2



def test_duplicate_storage_root_registration_is_rejected(db) -> None:
    seeded = seed_location(db)

    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            db.execute(
                """
                INSERT INTO storage_roots (id, display_name, uri, kind)
                VALUES (%s, 'Duplicate root', 'file:///tmp/brain-test', 'local')
                """,
                (uuid4(),),
            )

    root_count = db.execute(
        "SELECT count(*) FROM storage_roots WHERE id = %s",
        (seeded["root_id"],),
    ).fetchone()[0]
    assert root_count == 1



def test_scan_root_is_immutable_after_observations(db) -> None:
    seeded = seed_location(db)
    other_root_id = uuid4()
    db.execute(
        """
        INSERT INTO storage_roots (id, display_name, uri, kind)
        VALUES (%s, 'Other root', 'file:///tmp/other-root', 'local')
        """,
        (other_root_id,),
    )
    scan_id = create_scan(db, seeded["root_id"])
    add_observation(db, scan_id, "docs/readme.md")

    with pytest.raises(psycopg.errors.RaiseException, match="root is immutable"):
        with db.transaction():
            db.execute(
                "UPDATE scan_runs SET storage_root_id = %s WHERE id = %s",
                (other_root_id, scan_id),
            )


def test_asset_version_fingerprint_is_immutable(db) -> None:
    seeded = seed_location(db)

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with db.transaction():
            db.execute(
                "UPDATE asset_versions SET sha256 = %s WHERE id = %s",
                ("d" * 64, seeded["version_id"]),
            )

    fingerprint = db.execute(
        "SELECT sha256, size_bytes FROM asset_versions WHERE id = %s",
        (seeded["version_id"],),
    ).fetchone()
    assert fingerprint == ("a" * 64, 4)


def test_reconciliation_refuses_path_normalizer_version_mismatch(db) -> None:
    seeded = seed_location(db)
    db.execute(
        """
        UPDATE asset_locations
           SET path_normalizer_version = 'v0'
         WHERE id = %s
        """,
        (seeded["location_id"],),
    )
    scan_id = create_scan(db, seeded["root_id"])

    with pytest.raises(psycopg.errors.RaiseException, match="normalizer version mismatch"):
        with db.transaction():
            reconcile_complete_scan(db, scan_id)

    state = db.execute(
        "SELECT availability FROM asset_locations WHERE id = %s",
        (seeded["location_id"],),
    ).fetchone()[0]
    assert state == "available"


def test_scan_observation_normalizer_must_match_scan(db) -> None:
    seeded = seed_location(db)
    scan_id = create_scan(db, seeded["root_id"])

    with pytest.raises(psycopg.errors.RaiseException, match="must match"):
        with db.transaction():
            db.execute(
                """
                INSERT INTO scan_observations (
                    id, scan_run_id, relative_path, normalized_path_key,
                    path_normalizer_version, entry_kind
                )
                VALUES (%s, %s, 'docs/readme.md', 'docs/readme.md', 'v2', 'file')
                """,
                (uuid4(), scan_id),
            )


def test_pending_artifact_may_exist_without_output(db) -> None:
    seeded = seed_location(db)
    artifact_id = uuid4()
    db.execute(
        """
        INSERT INTO processing_artifacts (
            id, asset_version_id, artifact_type, processor_name,
            processor_version, status
        )
        VALUES (%s, %s, 'text', 'extractor', '1.0', 'pending')
        """,
        (artifact_id, seeded["version_id"]),
    )

    status = db.execute(
        "SELECT status FROM processing_artifacts WHERE id = %s",
        (artifact_id,),
    ).fetchone()[0]
    assert status == "pending"


def test_ready_artifact_requires_output(db) -> None:
    seeded = seed_location(db)

    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            db.execute(
                """
                INSERT INTO processing_artifacts (
                    id, asset_version_id, artifact_type, processor_name,
                    processor_version, status
                )
                VALUES (%s, %s, 'text', 'extractor', '1.0', 'ready')
                """,
                (uuid4(), seeded["version_id"]),
            )
