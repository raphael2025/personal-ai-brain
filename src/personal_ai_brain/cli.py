"""Command-line entry point for registry, extraction, and worker operations."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

from personal_ai_brain.assets.models import StorageKind, StorageRoot
from personal_ai_brain.assets.operations import PostgresAssetRegistryOperations
from personal_ai_brain.assets.scanner import ScanStatus
from personal_ai_brain.assets.service import AssetRegistryService
from personal_ai_brain.evaluation.postgres_search import PostgresLexicalSearchRepository
from personal_ai_brain.extractors.text import TextMarkdownExtractor
from personal_ai_brain.ingestion.artifacts import PostgresArtifactRepository
from personal_ai_brain.ingestion.models import JobSpec
from personal_ai_brain.ingestion.repository import PostgresJobRepository
from personal_ai_brain.workers.handlers import (
    TextExtractionHandler,
    text_extraction_config_digest,
)
from personal_ai_brain.workers.runtime import WorkerRuntime
from personal_ai_brain.workers.source_access import (
    AuthorizedSourceReader,
    PostgresWorkerSourceAccessRepository,
    load_worker_mount_map,
)


def _connection_factory():
    dsn = os.environ.get("PAB_DATABASE_URL")
    if not dsn:
        raise RuntimeError("Set PAB_DATABASE_URL to the PostgreSQL connection string")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support is optional; install personal-ai-brain[postgres]"
        ) from exc
    return lambda: psycopg.connect(dsn)


def _repository(connection_factory=None) -> PostgresAssetRegistryOperations:
    return PostgresAssetRegistryOperations(connection_factory or _connection_factory())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pab", description="Personal AI Brain CLI")
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

    extract = commands.add_parser("extract", help="enqueue extraction jobs")
    extract_commands = extract.add_subparsers(dest="extract_command", required=True)
    enqueue = extract_commands.add_parser(
        "enqueue", help="enqueue bounded text/Markdown extraction for an asset version"
    )
    enqueue.add_argument("--asset-version-id", required=True)
    enqueue.add_argument("--root-id", required=True)
    enqueue.add_argument("--max-attempts", type=int, default=3)

    worker = commands.add_parser("worker", help="manage and run local workers")
    worker_commands = worker.add_subparsers(dest="worker_command", required=True)
    register = worker_commands.add_parser("register", help="register or update a worker")
    register.add_argument("--worker-id", required=True)
    register.add_argument("--name", required=True)
    register.add_argument("--capability", action="append", required=True)

    grant = worker_commands.add_parser(
        "grant-root", help="grant a worker read access to one storage root"
    )
    grant.add_argument("--worker-id", required=True)
    grant.add_argument("--root-id", required=True)
    grant.add_argument("--actor", required=True)

    revoke = worker_commands.add_parser(
        "revoke-root", help="revoke a worker's read access to one storage root"
    )
    revoke.add_argument("--worker-id", required=True)
    revoke.add_argument("--root-id", required=True)
    revoke.add_argument("--actor", required=True)

    run = worker_commands.add_parser("run", help="run the pull-based local worker")
    run.add_argument("--worker-id", required=True)
    run.add_argument("--mounts-config", type=Path, required=True)
    run.add_argument("--lease-seconds", type=int, default=60)
    run.add_argument("--poll-interval", type=float, default=2.0)
    run.add_argument(
        "--once", action="store_true",
        help="claim and process at most one compatible job, then exit",
    )

    search = commands.add_parser("search", help="search persisted extracted text with BM25")
    search.add_argument("query")
    search.add_argument("--root-id")
    search.add_argument("--document-type")
    search.add_argument("--modified-after", type=_parse_datetime)
    search.add_argument("--modified-before", type=_parse_datetime)
    search.add_argument("--limit", type=int, default=10)

    return parser


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("datetime must be ISO-8601 with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone offset")
    return parsed


def _print_rows(rows: list[tuple[object, ...]]) -> None:
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))


def _run_worker(
    args: argparse.Namespace,
    connection_factory,
    jobs: PostgresJobRepository,
) -> int:
    worker_id = str(UUID(args.worker_id))
    mounts = load_worker_mount_map(
        args.mounts_config, expected_worker_id=worker_id
    )
    source_repository = PostgresWorkerSourceAccessRepository(connection_factory)
    source_reader = AuthorizedSourceReader(
        source_repository,
        mounts,
        max_bytes=TextMarkdownExtractor.MANIFEST.max_input_bytes,
    )
    artifact_repository = PostgresArtifactRepository(connection_factory)
    handler = TextExtractionHandler(source_reader, artifact_repository)
    runtime = WorkerRuntime(
        jobs,
        worker_id,
        {"extract_text": handler},
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
    )

    if args.once:
        processed = runtime.run_once()
        print(f"processed_one_job={processed}")
        return 0

    stop_event = Event()

    def request_stop(signum, _frame) -> None:
        print(
            f"received signal {signum}; finishing the active job before shutdown",
            file=sys.stderr,
        )
        stop_event.set()

    previous_handlers = {
        signum: signal.signal(signum, request_stop)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    print(f"worker={worker_id} started; press Ctrl+C to drain and stop")
    try:
        runtime.run_forever(stop_event)
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
    print(f"worker={worker_id} stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        connection_factory = _connection_factory()
        repository = _repository(connection_factory)
        service = AssetRegistryService(repository)
        jobs = PostgresJobRepository(connection_factory)

        if args.command == "worker" and args.worker_command == "register":
            worker_id = str(UUID(args.worker_id))
            jobs.register_worker(worker_id, args.name, tuple(args.capability))
            print(f"registered worker={worker_id} capabilities={','.join(args.capability)}")
            return 0

        if args.command == "worker" and args.worker_command in {"grant-root", "revoke-root"}:
            source_repository = PostgresWorkerSourceAccessRepository(connection_factory)
            worker_id = str(UUID(args.worker_id))
            root_id = str(UUID(args.root_id))
            if args.worker_command == "grant-root":
                source_repository.grant_root(worker_id, root_id, actor=args.actor)
                print(f"granted read_source worker={worker_id} root={root_id}")
            else:
                revoked = source_repository.revoke_root(
                    worker_id, root_id, actor=args.actor
                )
                print(
                    f"{'revoked' if revoked else 'no_active_grant'} "
                    f"worker={worker_id} root={root_id}"
                )
            return 0

        if args.command == "worker" and args.worker_command == "run":
            return _run_worker(args, connection_factory, jobs)

        if args.command == "search":
            search_repository = PostgresLexicalSearchRepository(connection_factory)
            results = search_repository.search(
                args.query,
                root_id=args.root_id,
                document_type=args.document_type,
                modified_after=args.modified_after,
                modified_before=args.modified_before,
                limit=args.limit,
            )
            for result in results:
                snippet = result.snippet.replace("\t", " ").replace("\n", " ")
                print(
                    f"{result.score:.6f}\\t{result.asset_id}\\t{result.asset_version_id}\\t"
                    f"{result.root_id}\\t{result.relative_path}\\t{result.source_sha256}\\t"
                    f"{snippet}"
                )
            if not results:
                print("no results")
            return 0

        if args.command == "extract" and args.extract_command == "enqueue":
            root_id = str(UUID(args.root_id))
            asset_version_id = str(UUID(args.asset_version_id))
            extractor = TextMarkdownExtractor()
            config_digest = text_extraction_config_digest(extractor)
            job = JobSpec(
                asset_version_id=asset_version_id,
                task_type="extract_text",
                semantic_version=extractor.MANIFEST.semantic_version,
                config_digest=config_digest,
                idempotency_key=(
                    f"text-extract:{root_id}:{asset_version_id}:{config_digest}"
                ),
                payload={"root_id": root_id},
                required_capabilities=("text",),
                max_attempts=args.max_attempts,
            )
            job_id = jobs.enqueue(job)
            print(f"job_id={job_id} task=extract_text asset_version={asset_version_id}")
            return 0

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
