"""PostgreSQL integration tests for read-only registry operations."""

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

from personal_ai_brain.assets.operations import PostgresAssetRegistryOperations  # noqa: E402

MIGRATION = (
    Path(__file__).parents[2]
    / "infrastructure"
    / "postgres"
    / "migrations"
    / "0001_asset_registry.sql"
)


@pytest.fixture
def registry():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_ops_test_{uuid4().hex}"
    try:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
        )
        connection.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.commit()
        yield PostgresAssetRegistryOperations(
            lambda: psycopg.connect(DATABASE_URL, options=f"-c search_path={schema_name}")
        ), connection
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def seed(registry):
    operations, connection = registry
    root_id, asset_id, version_id, location_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    connection.execute(
        """
        INSERT INTO storage_roots (id, display_name, uri, kind)
        VALUES (%s, 'Operations test', 'file:///tmp/pab-ops-test', 'local')
        """,
        (root_id,),
    )
    connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
    connection.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 12)
        """,
        (version_id, asset_id, "e" * 64),
    )
    connection.execute(
        """
        INSERT INTO asset_locations (
            id, asset_id, storage_root_id, current_version_id,
            relative_path, normalized_path_key, path_normalizer_version
        )
        VALUES (%s, %s, %s, %s, 'notes/example.md', 'notes/example.md', 'v1-exact')
        """,
        (location_id, asset_id, root_id, version_id),
    )
    connection.commit()
    return operations, connection, root_id, asset_id, location_id


def test_asset_list_and_inspect_are_read_only(registry):
    operations, connection, root_id, asset_id, location_id = seed(registry)

    rows = operations.list_assets(root_id=str(root_id))
    versions, locations = operations.inspect_asset(str(asset_id))

    assert len(rows) == 1
    assert rows[0][0] == asset_id
    assert len(versions) == 1
    assert len(locations) == 1
    assert locations[0][0] == location_id
    assert connection.execute(
        "SELECT availability FROM asset_locations WHERE id = %s", (location_id,)
    ).fetchone()[0] == "available"


def test_scan_history_lists_root_scans(registry):
    operations, connection, root_id, _, _ = seed(registry)
    scan_id = uuid4()
    connection.execute(
        """
        INSERT INTO scan_runs (
            id, storage_root_id, status, scanner_version, finished_at
        )
        VALUES (%s, %s, 'complete', 'test', now())
        """,
        (scan_id, root_id),
    )
    connection.commit()

    rows = operations.list_scans(root_id=str(root_id))
    assert len(rows) == 1
    assert rows[0][0] == scan_id


def test_reconciliation_preview_is_read_only(registry):
    operations, connection, root_id, _, location_id = seed(registry)
    scan_id = uuid4()
    connection.execute(
        """
        INSERT INTO scan_runs (
            id, storage_root_id, status, scanner_version,
            path_normalizer_version, finished_at
        )
        VALUES (%s, %s, 'complete', 'test', 'v1-exact', now())
        """,
        (scan_id, root_id),
    )
    connection.commit()

    scan, candidates = operations.preview_reconciliation(str(scan_id))

    assert scan[0] == scan_id
    assert [row[0] for row in candidates] == [location_id]
    assert connection.execute(
        "SELECT availability FROM asset_locations WHERE id = %s", (location_id,)
    ).fetchone()[0] == "available"


def test_reconciliation_preview_rejects_incomplete_scan(registry):
    operations, connection, root_id, _, _ = seed(registry)
    scan_id = uuid4()
    connection.execute(
        """
        INSERT INTO scan_runs (
            id, storage_root_id, status, scanner_version
        )
        VALUES (%s, %s, 'running', 'test')
        """,
        (scan_id, root_id),
    )
    connection.commit()

    with pytest.raises(ValueError, match="COMPLETE"):
        operations.preview_reconciliation(str(scan_id))


def test_inspect_rejects_unknown_asset(registry):
    operations, _, _, _, _ = seed(registry)

    with pytest.raises(LookupError, match="asset not found"):
        operations.inspect_asset(str(uuid4()))
