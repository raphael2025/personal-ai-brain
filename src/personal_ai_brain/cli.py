"""Command-line entry point for local Asset Registry operations."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4

from personal_ai_brain.assets.models import StorageKind, StorageRoot
from personal_ai_brain.assets.repository import PostgresAssetRegistryRepository
from personal_ai_brain.assets.service import AssetRegistryService


def _repository() -> PostgresAssetRegistryRepository:
    dsn = os.environ.get("PAB_DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set PAB_DATABASE_URL to the PostgreSQL connection string")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support is optional; install personal-ai-brain[postgres]"
        ) from exc
    return PostgresAssetRegistryRepository(lambda: psycopg.connect(dsn))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pab", description="Personal AI Brain registry CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    roots = commands.add_parser("root", help="manage storage roots")
    root_commands = roots.add_subparsers(dest="root_command", required=True)
    add = root_commands.add_parser("add", help="explicitly enroll a storage root")
    add.add_argument("--name", required=True)
    add.add_argument("--uri", required=True)
    add.add_argument("--kind", choices=[kind.value for kind in StorageKind], required=True)
    add.add_argument(
        "--case-sensitive",
        choices=("yes", "no", "unknown"),
        default="unknown",
        help="filesystem path case behavior; unknown uses exact path comparison",
    )
    root_commands.add_parser("list", help="list enrolled roots")

    scan = commands.add_parser("scan", help="scan an enrolled root")
    scan.add_argument("root_id")
    scan.add_argument(
        "--path",
        type=Path,
        help="explicit local mount path for SMB/NFS roots; does not change the stored URI",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository = _repository()
        service = AssetRegistryService(repository)

        if args.command == "root" and args.root_command == "add":
            root = StorageRoot(
                root_id=str(uuid4()),
                display_name=args.name,
                uri=args.uri,
                kind=StorageKind(args.kind),
            )
            case_sensitive = {
                "yes": True,
                "no": False,
                "unknown": None,
            }[args.case_sensitive]
            repository.register_root(root, path_case_sensitive=case_sensitive)
            print(f"registered root {root.root_id}")
            return 0

        if args.command == "root" and args.root_command == "list":
            for item in repository.list_roots():
                print(
                    f"{item.root.root_id}\t{item.root.kind.value}\t"
                    f"{item.root.display_name}\t{item.root.uri}\t"
                    f"{'enabled' if item.root.enabled else 'disabled'}"
                )
            return 0

        if args.command == "scan":
            execution = service.scan_root(args.root_id, local_path=args.path)
            print(
                f"scan={execution.scan_id} status={execution.result.status.value} "
                f"observations={len(execution.result.observations)} "
                f"issues={len(execution.result.issues)} "
                f"reconciliation_events={execution.reconciliation_events}"
            )
            for issue in execution.result.issues:
                print(
                    f"issue path={issue.relative_path} operation={issue.operation} "
                    f"error={issue.error_type}",
                    file=sys.stderr,
                )
            return 0 if execution.result.status is ScanStatus.COMPLETE else 2
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
