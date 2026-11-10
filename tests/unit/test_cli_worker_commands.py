"""Argument parsing tests for worker and extraction commands."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from personal_ai_brain.cli import _parser


def test_worker_register_and_root_grant_commands_parse():
    worker_id = str(uuid4())
    root_id = str(uuid4())

    register = _parser().parse_args(
        [
            "worker", "register", "--worker-id", worker_id,
            "--name", "local text worker", "--capability", "text",
        ]
    )
    grant = _parser().parse_args(
        [
            "worker", "grant-root", "--worker-id", worker_id,
            "--root-id", root_id, "--actor", "operator",
        ]
    )
    revoke = _parser().parse_args(
        [
            "worker", "revoke-root", "--worker-id", worker_id,
            "--root-id", root_id, "--actor", "operator",
        ]
    )

    assert register.worker_command == "register"
    assert register.capability == ["text"]
    assert grant.worker_command == "grant-root"
    assert revoke.worker_command == "revoke-root"


def test_search_command_parses_filters_and_timezone_aware_dates():
    root_id = str(uuid4())
    args = _parser().parse_args(
        [
            "search", "project notes", "--root-id", root_id,
            "--document-type", "MD", "--modified-after", "2025-01-01T00:00:00Z",
            "--limit", "5",
        ]
    )

    assert args.command == "search"
    assert args.root_id == root_id
    assert args.document_type == "MD"
    assert args.modified_after.tzinfo is not None
    assert args.limit == 5


def test_worker_run_and_extract_enqueue_commands_parse(tmp_path: Path):
    worker_id = str(uuid4())
    root_id = str(uuid4())
    version_id = str(uuid4())
    config = tmp_path / "worker.toml"

    run = _parser().parse_args(
        [
            "worker", "run", "--worker-id", worker_id,
            "--mounts-config", str(config), "--once",
        ]
    )
    enqueue = _parser().parse_args(
        [
            "extract", "enqueue", "--asset-version-id", version_id,
            "--root-id", root_id,
        ]
    )

    assert run.worker_command == "run"
    assert run.once is True
    assert run.mounts_config == config
    assert enqueue.extract_command == "enqueue"
    assert enqueue.max_attempts == 3
