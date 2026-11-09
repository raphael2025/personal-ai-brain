"""Integration tests for the Asset Registry application service."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("PERSONAL_AI_BRAIN_TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("PostgreSQL test database URL is not configured", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402

from personal_ai_brain.assets.models import StorageKind, StorageRoot  # noqa: E402
from personal_ai_brain.assets.repository import PostgresAssetRegistryRepository  # noqa: E402
from personal_ai_brain.assets.scanner import ScanIssue, ScanResult, ScanStatus  # noqa: E402
from personal_ai_brain.assets.service import AssetRegistryService  # noqa: E402

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
    schema_name = f"brain_service_test_{uuid4().hex}"
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


def _repository(db) -> PostgresAssetRegistryRepository:
    return PostgresAssetRegistryRepository(lambda: db, close_connections=False)


def _enroll(
    repository: PostgresAssetRegistryRepository, path: Path
) -> StorageRoot:
    root = StorageRoot(
        root_id=str(uuid4()),
        display_name="Integration fixture",
        uri=path.as_uri(),
        kind=StorageKind.LOCAL,
    )
    repository.register_root(root, path_case_sensitive=True)
    return root


def test_scan_registers_asset_and_new_content_version(db, tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("first version", encoding="utf-8")
    repository = _repository(db)
    root = _enroll(repository, tmp_path)
    service = AssetRegistryService(repository)

    first = service.scan_root(root.root_id)
    assert first.result.status is ScanStatus.COMPLETE

    counts = db.execute(
        """
        SELECT
            (SELECT count(*) FROM assets),
            (SELECT count(*) FROM asset_versions),
            (SELECT count(*) FROM asset_locations),
            (SELECT count(*) FROM scan_observations)
        """
    ).fetchone()
    assert counts == (1, 1, 1, 1)

    source.write_text("second version has more bytes", encoding="utf-8")
    second = service.scan_root(root.root_id)
    assert second.result.status is ScanStatus.COMPLETE

    counts = db.execute(
        """
        SELECT
            (SELECT count(*) FROM assets),
            (SELECT count(*) FROM asset_versions),
            (SELECT count(*) FROM asset_locations),
            (SELECT count(*) FROM asset_location_events
              WHERE event_type = 'version_changed')
        """
    ).fetchone()
    assert counts == (1, 2, 1, 1)


def test_partial_scan_never_marks_unobserved_location_missing(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from personal_ai_brain.assets import service as service_module

    source = tmp_path / "keep.txt"
    source.write_text("keep", encoding="utf-8")
    repository = _repository(db)
    root = _enroll(repository, tmp_path)
    service = AssetRegistryService(repository)
    first = service.scan_root(root.root_id)
    assert first.result.status is ScanStatus.COMPLETE

    now = datetime.now(UTC)
    monkeypatch.setattr(
        service_module,
        "scan_directory",
        lambda path: ScanResult(
            root=path,
            status=ScanStatus.PARTIAL,
            observations=(),
            issues=(ScanIssue(".", "read_directory", "PermissionError"),),
            started_at=now,
            finished_at=now,
        ),
    )
    partial = service.scan_root(root.root_id)
    assert partial.result.status is ScanStatus.PARTIAL

    availability = db.execute(
        "SELECT availability FROM asset_locations"
    ).fetchone()[0]
    assert availability == "available"


def test_complete_empty_scan_marks_previous_location_missing(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from personal_ai_brain.assets import service as service_module

    source = tmp_path / "gone.txt"
    source.write_text("temporary", encoding="utf-8")
    repository = _repository(db)
    root = _enroll(repository, tmp_path)
    service = AssetRegistryService(repository)
    first = service.scan_root(root.root_id)
    assert first.result.status is ScanStatus.COMPLETE
    source.unlink()

    now = datetime.now(UTC)
    monkeypatch.setattr(
        service_module,
        "scan_directory",
        lambda path: ScanResult(
            root=path,
            status=ScanStatus.COMPLETE,
            observations=(),
            issues=(),
            started_at=now,
            finished_at=now,
        ),
    )
    empty = service.scan_root(root.root_id)
    assert empty.result.status is ScanStatus.COMPLETE
    availability = db.execute(
        "SELECT availability FROM asset_locations"
    ).fetchone()[0]
    assert availability == "missing"


def test_network_root_requires_explicit_local_mount_path(db, tmp_path: Path) -> None:
    repository = _repository(db)
    root = StorageRoot(
        root_id=str(uuid4()),
        display_name="NAS",
        uri="smb://nas.example/private",
        kind=StorageKind.NETWORK,
    )
    repository.register_root(root)

    service = AssetRegistryService(repository)
    with pytest.raises(ValueError, match="explicit mounted path"):
        service.scan_root(root.root_id)

    count = db.execute("SELECT count(*) FROM scan_runs").fetchone()[0]
    assert count == 0
