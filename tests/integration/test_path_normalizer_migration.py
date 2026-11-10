"""PostgreSQL tests for explicit path-normalizer migration."""

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

from personal_ai_brain.assets.models import StorageKind, StorageRoot  # noqa: E402
from personal_ai_brain.assets.repository import (  # noqa: E402
    PathNormalizerCollisionError,
    PostgresAssetRegistryRepository,
)

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
    schema_name = f"brain_normalizer_test_{uuid4().hex}"
    try:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
        )
        connection.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.commit()
        repository = PostgresAssetRegistryRepository(
            lambda: psycopg.connect(
                DATABASE_URL, options=f"-c search_path={schema_name}"
            )
        )
        yield repository, connection
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def add_location(repository, connection, path: str) -> tuple[str, str]:
    root_id, asset_id, version_id, location_id = (
        str(uuid4()), uuid4(), uuid4(), uuid4()
    )
    if not connection.execute(
        "SELECT 1 FROM storage_roots WHERE id = %s", (root_id,)
    ).fetchone():
        repository.register_root(
            StorageRoot(
                root_id=root_id,
                display_name="Normalizer test",
                uri=f"file:///tmp/normalizer-{root_id}",
                kind=StorageKind.LOCAL,
            ),
            path_case_sensitive=True,
        )
    connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
    connection.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 4)
        """,
        (version_id, asset_id, "d" * 64, ),
    )
    connection.execute(
        """
        INSERT INTO asset_locations (
            id, asset_id, storage_root_id, current_version_id,
            relative_path, normalized_path_key, path_normalizer_version
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'v1-exact')
        """,
        (location_id, asset_id, root_id, version_id, path, path),
    )
    connection.commit()
    return root_id, str(location_id)


def test_preview_is_read_only_and_apply_is_audited(registry):
    repository, connection = registry
    root_id, location_id = add_location(repository, connection, "Folder/Readme.md")

    plan = repository.preview_path_normalizer_migration(
        root_id, target_version="v1-casefold"
    )
    assert plan.from_version == "v1-exact"
    assert plan.to_version == "v1-casefold"
    assert len(plan.changes) == 1
    assert plan.changes[0].target_key == "folder/readme.md"
    assert plan.applied is False

    assert connection.execute(
        "SELECT path_normalizer_version FROM storage_roots WHERE id = %s",
        (root_id,),
    ).fetchone()[0] == "v1-exact"
    assert connection.execute(
        "SELECT normalized_path_key FROM asset_locations WHERE id = %s",
        (location_id,),
    ).fetchone()[0] == "Folder/Readme.md"

    applied = repository.apply_path_normalizer_migration(
        root_id, target_version="v1-casefold", actor="test-operator"
    )
    assert applied.applied is True
    assert connection.execute(
        "SELECT path_normalizer_version FROM storage_roots WHERE id = %s",
        (root_id,),
    ).fetchone()[0] == "v1-casefold"
    assert connection.execute(
        "SELECT normalized_path_key, path_normalizer_version FROM asset_locations WHERE id = %s",
        (location_id,),
    ).fetchone() == ("folder/readme.md", "v1-casefold")
    assert connection.execute(
        """
        SELECT actor, action, decision
          FROM audit_events
         WHERE target_id = %s
        """,
        (root_id,),
    ).fetchone() == (
        "test-operator",
        "storage_root.path_normalizer_migrate",
        "recorded",
    )

    scan_id = repository.start_scan(root_id, scanner_version="migration-test")
    assert connection.execute(
        "SELECT path_normalizer_version FROM scan_runs WHERE id = %s",
        (scan_id,),
    ).fetchone()[0] == "v1-casefold"


def test_collision_preview_refuses_apply_without_merging(registry):
    repository, connection = registry
    root_id, first_id = add_location(repository, connection, "Docs/Readme.md")
    second_asset, second_version, second_location = uuid4(), uuid4(), uuid4()
    connection.execute("INSERT INTO assets (id) VALUES (%s)", (second_asset,))
    connection.execute(
        """
        INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
        VALUES (%s, %s, %s, 4)
        """,
        (second_version, second_asset, "e" * 64),
    )
    connection.execute(
        """
        INSERT INTO asset_locations (
            id, asset_id, storage_root_id, current_version_id,
            relative_path, normalized_path_key, path_normalizer_version
        )
        VALUES (%s, %s, %s, %s, 'docs/readme.md', 'docs/readme.md', 'v1-exact')
        """,
        (second_location, second_asset, root_id, second_version),
    )
    connection.commit()

    plan = repository.preview_path_normalizer_migration(
        root_id, target_version="v1-casefold"
    )
    assert len(plan.collisions) == 1
    assert set(plan.collisions[0].location_ids) == {first_id, str(second_location)}

    with pytest.raises(PathNormalizerCollisionError):
        repository.apply_path_normalizer_migration(
            root_id, target_version="v1-casefold", actor="test-operator"
        )

    assert connection.execute(
        "SELECT path_normalizer_version FROM storage_roots WHERE id = %s",
        (root_id,),
    ).fetchone()[0] == "v1-exact"
    assert connection.execute(
        """
        SELECT count(*) FROM asset_locations
         WHERE storage_root_id = %s AND path_normalizer_version = 'v1-exact'
        """,
        (root_id,),
    ).fetchone()[0] == 2


def test_migration_is_blocked_while_scan_is_running(registry):
    repository, connection = registry
    root_id, _ = add_location(repository, connection, "Docs/One.md")
    repository.start_scan(root_id, scanner_version="running-scan")

    with pytest.raises(ValueError, match="pending or running scans"):
        repository.apply_path_normalizer_migration(
            root_id, target_version="v1-casefold", actor="test-operator"
        )


def test_audit_failure_rolls_back_all_normalizer_changes(registry):
    repository, connection = registry
    root_id, location_id = add_location(repository, connection, "Docs/One.md")
    connection.execute(
        """
        CREATE FUNCTION reject_path_migration_audit() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.action = 'storage_root.path_normalizer_migrate' THEN
                RAISE EXCEPTION 'injected audit failure';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    connection.execute(
        """
        CREATE TRIGGER reject_path_migration_audit
        BEFORE INSERT ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_path_migration_audit()
        """
    )
    connection.commit()

    with pytest.raises(psycopg.Error, match="injected audit failure"):
        repository.apply_path_normalizer_migration(
            root_id, target_version="v1-casefold", actor="test-operator"
        )

    assert connection.execute(
        "SELECT path_normalizer_version FROM storage_roots WHERE id = %s",
        (root_id,),
    ).fetchone()[0] == "v1-exact"
    assert connection.execute(
        "SELECT normalized_path_key FROM asset_locations WHERE id = %s",
        (location_id,),
    ).fetchone()[0] == "Docs/One.md"
