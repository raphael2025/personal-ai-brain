"""Tests for worker-local storage-root mount configuration."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from personal_ai_brain.workers.source_access import (
    WorkerMountMap,
    load_worker_mount_map,
)


def test_loads_mount_map_and_normalizes_root_ids(tmp_path: Path):
    worker_id = str(uuid4())
    root_id = str(uuid4())
    mount = tmp_path / "documents"
    mount.mkdir()
    config = tmp_path / "worker.toml"
    config.write_text(
        f'version = 1\nworker_id = "{worker_id}"\n\n[mounts]\n"{root_id.upper()}" = "{mount}"\n',
        encoding="utf-8",
    )

    result = load_worker_mount_map(config, expected_worker_id=worker_id)

    assert result.worker_id == worker_id
    assert result.mounts[str(UUID(root_id))] == mount


def test_rejects_relative_mount_paths():
    with pytest.raises(ValueError, match="absolute"):
        WorkerMountMap(str(uuid4()), {str(uuid4()): Path("relative/path")})


def test_rejects_unknown_or_missing_config_fields(tmp_path: Path):
    config = tmp_path / "worker.toml"
    config.write_text('version = 1\nworker_id = "x"\n[mounts]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="mount config"):
        load_worker_mount_map(config)


def test_rejects_worker_id_mismatch(tmp_path: Path):
    worker_id = str(uuid4())
    config = tmp_path / "worker.toml"
    config.write_text(
        f'version = 1\nworker_id = "{uuid4()}"\n[mounts]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        load_worker_mount_map(config, expected_worker_id=worker_id)
