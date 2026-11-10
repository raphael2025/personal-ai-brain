"""Command-line entry point for local Asset Registry operations."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4

from personal_ai_brain.assets.models import StorageKind, StorageRoot
from personal_ai_brain.assets.operations import PostgresAssetRegistryOperations
from personal_ai_brain.assets.scanner import ScanStatus
from personal_ai_brain.assets.service import AssetRegistryService


def _repository() -> PostgresAssetRegistryOperations:
    dsn = os.environ.get("PAB_DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set PAB_DATABASE_URL to the PostgreSQL connection string")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support is optional; install personal-ai-brain[postgres]"
        ) from exc
    return PostgresAssetRegistryOperations(lambda: psycopg.connect(dsn))


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
    migrate = root_commands.add_parser(
        "migrate-normalizer", help="preview or apply a storage-root path-key migration"
    )
    migrate.add_argument("root_id")
    migrate.add_argument(
        "--target-version", choices=("v1-exact", "v1-casefold"), required=True
    )
    migrate.add_argument(
        "--apply", action="store_true",
        help="apply after reviewing the preview; otherwise this command is read-only",
    )
    migrate.add_argument("--actor", help="operator identity required with --apply")

    scan = commands.add_parser("scan", help="scan an enrolled root")
    scan.add_argument("root_id")
    scan.add_argument(
        "--path",
        type=Path,
        help="explicit local mount path for SMB/NFS roots; does not change the stored URI",
    )

    scan_status = commands.add_parser("scan-status", help="show recent scan history")
    scan_status.add_argument("--root-id")
    scan_status.add_argument("--limit", type=int, default=50)

    assets = commands.add_parser("asset", help="inspect registered assets")
    asset_commands = assets.add_subparsers(dest="asset_command", required=True)
    asset_list = asset_commands.add_parser("list", help="list current asset locations")
    asset_list.add_argument("--root-id")
    asset_list.add_argument("--limit", type=int, default=100)
    asset_list.add_argument("--offset", type=int, default=0)
    asset_inspect = asset_commands.add_parser("inspect", help="show versions and locations")
    asset_inspect.add_argument("asset_id")

    reconcile = commands.add_parser("reconcile", help="inspect reconciliation candidates")
    reconcile_commands = reconcile.add_subparsers(dest="reconcile_command", required=True)
    preview = reconcile_commands.add_parser(
        "preview", help="dry-run; list locations a COMPLETE scan would mark missing"
    )
    preview.add_argument("scan_id")
    apply = reconcile_commands.add_parser(
        "apply", help="apply reconciliation for a COMPLETE scan and write an audit event"
    )
    apply.add_argument("scan_id")
    apply.add_argument("--actor", required=True, help="human or automation identity")

    return parser


def _print_rows(rows: list[tuple[object, ...]]) -> None:
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))


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

        if args.command == "root" and args.root_command == "migrate-normalizer":
            if args.apply:
                if not args.actor:
                    raise ValueError("--actor is required with --apply")
                plan = repository.apply_path_normalizer_migration(
                    args.root_id,
                    target_version=args.target_version,
                    actor=args.actor,
                )
            else:
                plan = repository.preview_path_normalizer_migration(
                    args.root_id, target_version=args.target_version
                )
            print(
                f"root={plan.root_id} from={plan.from_version} to={plan.to_version} "
                f"locations={len(plan.changes)} collisions={len(plan.collisions)} "
                f"applied={plan.applied}"
            )
            for change in plan.changes:
                print(
                    f"location={change.location_id} path={change.relative_path!r} "
                    f"{change.previous_key!r} -> {change.target_key!r}"
                )
            for collision in plan.collisions:
                print(
                    f"COLLISION key={collision.target_key!r} "
                    f"locations={','.join(collision.location_ids)}"
                )
            if not args.apply:
                print("DRY RUN ONLY: no registry rows were changed.")
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
                    f"issue path={issue.relative_path!r} operation={issue.operation} "
                    f"error={issue.error_type}",
                    file=sys.stderr,
                )
            return 0 if execution.result.status is ScanStatus.COMPLETE else 2

        if args.command == "scan-status":
            _print_rows(repository.list_scans(root_id=args.root_id, limit=args.limit))
            return 0

        if args.command == "asset" and args.asset_command == "list":
            _print_rows(
                repository.list_assets(
                    root_id=args.root_id, limit=args.limit, offset=args.offset
                )
            )
            return 0

        if args.command == "asset" and args.asset_command == "inspect":
            versions, locations = repository.inspect_asset(args.asset_id)
            print("VERSIONS")
            _print_rows(versions)
            print("LOCATIONS")
            _print_rows(locations)
            return 0

        if args.command == "reconcile" and args.reconcile_command == "preview":
            scan, candidates = repository.preview_reconciliation(args.scan_id)
            print(f"scan_id={scan[0]} root_id={scan[1]} status={scan[2]}")
            print(f"would_mark_missing={len(candidates)}")
            _print_rows(candidates)
            print("DRY RUN ONLY: no registry rows were changed.")
            return 0

        if args.command == "reconcile" and args.reconcile_command == "apply":
            changed = repository.reconcile_scan(args.scan_id, actor=args.actor)
            print(
                f"scan={args.scan_id} reconciliation_events={changed} "
                f"actor={args.actor}"
            )
            return 0
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
