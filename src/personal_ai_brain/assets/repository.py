"""PostgreSQL adapter for the Asset Registry.

The domain layer stays DB-driver agnostic. This adapter accepts a DB-API connection
factory, allowing tests to inject an existing transaction and applications to load
psycopg only when PostgreSQL persistence is selected.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from personal_ai_brain.assets.models import StorageKind, StorageRoot
from personal_ai_brain.assets.scanner import EntryKind, ScanObservation, ScanStatus


@dataclass(frozen=True, slots=True)
class StorageRootRecord:
    root: StorageRoot
    path_case_sensitive: bool | None
    path_normalizer_version: str


@dataclass(frozen=True, slots=True)
class PathNormalizerChange:
    location_id: str
    relative_path: str
    previous_key: str
    target_key: str


@dataclass(frozen=True, slots=True)
class PathNormalizerCollision:
    target_key: str
    location_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathNormalizerMigrationPlan:
    root_id: str
    from_version: str
    to_version: str
    changes: tuple[PathNormalizerChange, ...]
    collisions: tuple[PathNormalizerCollision, ...]
    applied: bool = False


@dataclass(frozen=True, slots=True)
class PreparedObservation:
    observation: ScanObservation
    sha256: str | None = None
    size_bytes: int | None = None


class AssetRegistryRepository(Protocol):
    def register_root(
        self, root: StorageRoot, *, path_case_sensitive: bool | None = None
    ) -> None: ...

    def get_root(self, root_id: str) -> StorageRootRecord: ...

    def list_roots(self) -> list[StorageRootRecord]: ...

    def start_scan(self, root_id: str, *, scanner_version: str) -> str: ...

    def finish_scan(
        self,
        scan_id: str,
        observations: list[PreparedObservation],
        *,
        status: ScanStatus,
        error_summary: str | None = None,
    ) -> int: ...

    def reconcile_scan(self, scan_id: str, *, actor: str) -> int: ...

    def preview_path_normalizer_migration(
        self, root_id: str, *, target_version: str
    ) -> PathNormalizerMigrationPlan: ...

    def apply_path_normalizer_migration(
        self, root_id: str, *, target_version: str, actor: str
    ) -> PathNormalizerMigrationPlan: ...

    def fail_scan(self, scan_id: str, error_summary: str) -> None: ...


class RegistryNotFoundError(LookupError):
    """A requested registry object does not exist."""


class PathNormalizerMigrationRequired(RuntimeError):
    """Active location keys need explicit migration before scanning can reconcile."""


class PathNormalizerCollisionError(RuntimeError):
    """A target normalizer would make distinct active locations collide."""


class IdempotencyConflict(RuntimeError):
    """A repeated scan finalization differs from the already committed result."""


class PostgresAssetRegistryRepository:
    """Transactional PostgreSQL implementation of the registry repository."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        close_connections: bool = True,
    ) -> None:
        self._connect = connection_factory
        self._close_connections = close_connections

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection.transaction():
                yield connection
        finally:
            if self._close_connections:
                connection.close()

    @staticmethod
    def _uuid(value: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("registry IDs must be UUID strings") from exc

    @staticmethod
    def _root_record(row: tuple[Any, ...]) -> StorageRootRecord:
        root_id, name, uri, kind, enabled, follow_symlinks, case_sensitive, normalizer = row
        return StorageRootRecord(
            root=StorageRoot(
                root_id=str(root_id),
                display_name=name,
                uri=uri,
                kind=StorageKind(kind),
                enabled=enabled,
                follow_symlinks=follow_symlinks,
            ),
            path_case_sensitive=case_sensitive,
            path_normalizer_version=normalizer,
        )

    def register_root(
        self, root: StorageRoot, *, path_case_sensitive: bool | None = None
    ) -> None:
        if path_case_sensitive is not None and type(path_case_sensitive) is not bool:
            raise ValueError("path_case_sensitive must be a boolean or None")
        normalizer = "v1-casefold" if path_case_sensitive is False else "v1-exact"
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO storage_roots (
                    id, display_name, uri, kind, enabled, follow_symlinks,
                    path_case_sensitive, path_normalizer_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._uuid(root.root_id),
                    root.display_name,
                    root.uri,
                    root.kind.value,
                    root.enabled,
                    root.follow_symlinks,
                    path_case_sensitive,
                    normalizer,
                ),
            )

    def get_root(self, root_id: str) -> StorageRootRecord:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, display_name, uri, kind, enabled, follow_symlinks,
                       path_case_sensitive, path_normalizer_version
                  FROM storage_roots
                 WHERE id = %s
                """,
                (self._uuid(root_id),),
            ).fetchone()
        if row is None:
            raise RegistryNotFoundError(f"storage root not found: {root_id}")
        return self._root_record(row)

    def list_roots(self) -> list[StorageRootRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, display_name, uri, kind, enabled, follow_symlinks,
                       path_case_sensitive, path_normalizer_version
                  FROM storage_roots
                 ORDER BY display_name, id
                """
            ).fetchall()
        return [self._root_record(row) for row in rows]

    def _path_normalizer_migration(
        self,
        root_id: str,
        *,
        target_version: str,
        actor: str | None,
    ) -> PathNormalizerMigrationPlan:
        root_uuid = self._uuid(root_id)
        if target_version not in {"v1-exact", "v1-casefold"}:
            raise ValueError("target_version must be v1-exact or v1-casefold")
        if actor is not None:
            if not isinstance(actor, str) or not actor.strip() or len(actor) > 200:
                raise ValueError("actor must be non-empty and at most 200 characters")
            if any(ord(char) < 0x20 or ord(char) == 0x7F for char in actor):
                raise ValueError("actor must not contain ASCII control characters")

        with self._connection() as connection:
            root = connection.execute(
                """
                SELECT path_normalizer_version
                  FROM storage_roots
                 WHERE id = %s
                 FOR UPDATE
                """,
                (root_uuid,),
            ).fetchone()
            if root is None:
                raise RegistryNotFoundError(f"storage root not found: {root_id}")
            current_version = root[0]

            if current_version not in {"v1-exact", "v1-casefold"}:
                raise ValueError(f"unsupported current path normalizer: {current_version}")

            running_scans = connection.execute(
                """
                SELECT count(*) FROM scan_runs
                 WHERE storage_root_id = %s
                   AND status IN ('pending', 'running')
                """,
                (root_uuid,),
            ).fetchone()[0]
            if running_scans:
                raise ValueError("path normalizer migration is blocked by pending or running scans")

            rows = connection.execute(
                """
                SELECT id, relative_path, normalized_path_key, path_normalizer_version
                  FROM asset_locations
                 WHERE storage_root_id = %s AND valid_to IS NULL
                 ORDER BY relative_path, id
                 FOR UPDATE
                """,
                (root_uuid,),
            ).fetchall()

            changes: list[PathNormalizerChange] = []
            by_target_key: dict[str, list[str]] = {}
            for location_id, relative_path, previous_key, stored_version in rows:
                if stored_version != current_version:
                    raise PathNormalizerMigrationRequired(
                        "active locations do not share the storage root's current normalizer"
                    )
                target_key = self._normalized_key(relative_path, target_version)
                changes.append(
                    PathNormalizerChange(
                        location_id=str(location_id),
                        relative_path=relative_path,
                        previous_key=previous_key,
                        target_key=target_key,
                    )
                )
                by_target_key.setdefault(target_key, []).append(str(location_id))

            collisions = tuple(
                PathNormalizerCollision(target_key=key, location_ids=tuple(ids))
                for key, ids in sorted(by_target_key.items())
                if len(ids) > 1
            )
            plan = PathNormalizerMigrationPlan(
                root_id=str(root_uuid),
                from_version=current_version,
                to_version=target_version,
                changes=tuple(changes),
                collisions=collisions,
                applied=False,
            )

            if collisions:
                if actor is not None:
                    raise PathNormalizerCollisionError(
                        f"normalizer migration would collide at {len(collisions)} path key(s)"
                    )
                return plan

            if actor is None or current_version == target_version:
                return plan

            for change in changes:
                connection.execute(
                    """
                    UPDATE asset_locations
                       SET normalized_path_key = %s,
                           path_normalizer_version = %s
                     WHERE id = %s AND storage_root_id = %s
                       AND valid_to IS NULL
                    """,
                    (
                        change.target_key,
                        target_version,
                        self._uuid(change.location_id),
                        root_uuid,
                    ),
                )

            connection.execute(
                """
                UPDATE storage_roots
                   SET path_normalizer_version = %s, updated_at = now()
                 WHERE id = %s
                """,
                (target_version, root_uuid),
            )
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, actor, action, target_type, target_id, decision, details
                )
                VALUES (%s, %s, 'storage_root.path_normalizer_migrate',
                        'storage_root', %s, 'recorded', %s::jsonb)
                """,
                (
                    uuid4(),
                    actor.strip(),
                    str(root_uuid),
                    json.dumps(
                        {
                            "from_version": current_version,
                            "to_version": target_version,
                            "active_locations": len(changes),
                            "collisions": 0,
                        }
                    ),
                ),
            )

            return PathNormalizerMigrationPlan(
                root_id=str(root_uuid),
                from_version=current_version,
                to_version=target_version,
                changes=tuple(changes),
                collisions=(),
                applied=True,
            )

    def preview_path_normalizer_migration(
        self, root_id: str, *, target_version: str
    ) -> PathNormalizerMigrationPlan:
        return self._path_normalizer_migration(
            root_id, target_version=target_version, actor=None
        )

    def apply_path_normalizer_migration(
        self, root_id: str, *, target_version: str, actor: str
    ) -> PathNormalizerMigrationPlan:
        return self._path_normalizer_migration(
            root_id, target_version=target_version, actor=actor
        )

    def start_scan(self, root_id: str, *, scanner_version: str) -> str:
        scan_id = uuid4()
        root_uuid = self._uuid(root_id)
        with self._connection() as connection:
            root = connection.execute(
                """
                SELECT path_normalizer_version, enabled
                  FROM storage_roots
                 WHERE id = %s
                 FOR UPDATE
                """,
                (root_uuid,),
            ).fetchone()
            if root is None:
                raise RegistryNotFoundError(f"storage root not found: {root_id}")
            normalizer_version, enabled = root
            if not enabled:
                raise ValueError("storage root is disabled")

            mismatch = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                      FROM asset_locations
                     WHERE storage_root_id = %s
                       AND valid_to IS NULL
                       AND path_normalizer_version <> %s
                )
                """,
                (root_uuid, normalizer_version),
            ).fetchone()[0]
            if mismatch:
                raise PathNormalizerMigrationRequired(
                    "active location keys must be migrated before scanning this root"
                )

            connection.execute(
                """
                INSERT INTO scan_runs (
                    id, storage_root_id, status, scanner_version,
                    path_normalizer_version
                )
                VALUES (%s, %s, 'running', %s, %s)
                """,
                (scan_id, root_uuid, scanner_version, normalizer_version),
            )
        return str(scan_id)

    @staticmethod
    def _normalized_key(relative_path: str, normalizer_version: str) -> str:
        normalized = relative_path
        if normalizer_version.endswith("-casefold"):
            return normalized.casefold()
        return normalized

    def finish_scan(
        self,
        scan_id: str,
        observations: list[PreparedObservation],
        *,
        status: ScanStatus,
        error_summary: str | None = None,
    ) -> int:
        scan_uuid = self._uuid(scan_id)
        if status not in {ScanStatus.COMPLETE, ScanStatus.PARTIAL, ScanStatus.FAILED}:
            raise ValueError("scan must finish as complete, partial, or failed")

        with self._connection() as connection:
            scan = connection.execute(
                """
                SELECT storage_root_id, path_normalizer_version, status, error_summary
                  FROM scan_runs
                 WHERE id = %s
                 FOR UPDATE
                """,
                (scan_uuid,),
            ).fetchone()
            if scan is None:
                raise RegistryNotFoundError(f"scan not found: {scan_id}")
            root_id, normalizer_version, stored_status, stored_error = scan

            if stored_status != "running":
                expected = sorted(
                    (
                        (
                            item.observation.relative_path,
                            self._normalized_key(
                                item.observation.relative_path, normalizer_version
                            ),
                            normalizer_version,
                            item.observation.kind.value,
                            item.observation.size_bytes,
                            item.observation.modified_time_ns,
                            item.sha256,
                            item.size_bytes,
                        )
                        for item in observations
                    ),
                    key=lambda row: row[0],
                )
                existing = connection.execute(
                    """
                    SELECT o.relative_path, o.normalized_path_key,
                           o.path_normalizer_version, o.entry_kind,
                           o.size_bytes, o.modified_time_ns, v.sha256, v.size_bytes
                      FROM scan_observations AS o
                      LEFT JOIN asset_versions AS v ON v.id = o.asset_version_id
                     WHERE o.scan_run_id = %s
                     ORDER BY o.relative_path
                    """,
                    (scan_uuid,),
                ).fetchall()
                if (
                    stored_status != status.value
                    or stored_error != error_summary
                    or existing != expected
                ):
                    raise IdempotencyConflict(
                        "scan finalization was already committed with different data"
                    )
                return int(
                    connection.execute(
                        """
                        SELECT count(*)
                          FROM asset_location_events
                         WHERE scan_run_id = %s
                           AND event_type = 'availability_changed'
                        """,
                        (scan_uuid,),
                    ).fetchone()[0]
                )

            for prepared in observations:
                observation = prepared.observation
                path_key = self._normalized_key(
                    observation.relative_path, normalizer_version
                )
                version_id = None

                if observation.kind is EntryKind.FILE and prepared.sha256 is not None:
                    existing_location = connection.execute(
                        """
                        SELECT id, asset_id, current_version_id, relative_path
                          FROM asset_locations
                         WHERE storage_root_id = %s
                           AND normalized_path_key = %s
                           AND valid_to IS NULL
                         FOR UPDATE
                        """,
                        (root_id, path_key),
                    ).fetchone()

                    if existing_location is None:
                        asset_id = uuid4()
                        location_id = uuid4()
                        connection.execute(
                            "INSERT INTO assets (id) VALUES (%s)", (asset_id,)
                        )
                    else:
                        location_id = existing_location[0]
                        asset_id = existing_location[1]

                    version = connection.execute(
                        """
                        SELECT id
                          FROM asset_versions
                         WHERE asset_id = %s AND sha256 = %s AND size_bytes = %s
                        """,
                        (asset_id, prepared.sha256, prepared.size_bytes),
                    ).fetchone()
                    if version is None:
                        version_id = uuid4()
                        connection.execute(
                            """
                            INSERT INTO asset_versions (id, asset_id, sha256, size_bytes)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (version_id, asset_id, prepared.sha256, prepared.size_bytes),
                        )
                    else:
                        version_id = version[0]

                    if existing_location is None:
                        connection.execute(
                            """
                            INSERT INTO asset_locations (
                                id, asset_id, storage_root_id, current_version_id,
                                relative_path, normalized_path_key,
                                path_normalizer_version, availability
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'available')
                            """,
                            (
                                location_id,
                                asset_id,
                                root_id,
                                version_id,
                                observation.relative_path,
                                path_key,
                                normalizer_version,
                            ),
                        )
                    else:
                        (
                            location_id,
                            asset_id,
                            current_version_id,
                            current_relative_path,
                        ) = existing_location
                        if (
                            current_version_id != version_id
                            or observation.relative_path != current_relative_path
                        ):
                            connection.execute(
                                """
                                UPDATE asset_locations
                                   SET current_version_id = %s, relative_path = %s
                                 WHERE id = %s
                                """,
                                (version_id, observation.relative_path, location_id),
                            )
                        if current_version_id != version_id:
                            connection.execute(
                                """
                                INSERT INTO asset_location_events (
                                    id, asset_location_id, scan_run_id, event_type,
                                    previous_version_id, new_version_id
                                )
                                VALUES (%s, %s, %s, 'version_changed', %s, %s)
                                """,
                                (
                                    uuid4(),
                                    location_id,
                                    scan_uuid,
                                    current_version_id,
                                    version_id,
                                ),
                            )

                connection.execute(
                    """
                    INSERT INTO scan_observations (
                        id, scan_run_id, relative_path, normalized_path_key,
                        path_normalizer_version, entry_kind, size_bytes,
                        modified_time_ns, asset_version_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid4(),
                        scan_uuid,
                        observation.relative_path,
                        path_key,
                        normalizer_version,
                        observation.kind.value,
                        observation.size_bytes,
                        observation.modified_time_ns,
                        version_id,
                    ),
                )

            connection.execute(
                """
                UPDATE scan_runs
                   SET status = %s, finished_at = now(), error_summary = %s
                 WHERE id = %s AND status = 'running'
                """,
                (status.value, error_summary, scan_uuid),
            )

        return 0

    def reconcile_scan(self, scan_id: str, *, actor: str) -> int:
        """Apply COMPLETE-scan reconciliation as an explicit audited action."""
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 200:
            raise ValueError("actor must be a non-empty string of at most 200 characters")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in actor):
            raise ValueError("actor must not contain ASCII control characters")

        scan_uuid = self._uuid(scan_id)
        with self._connection() as connection:
            scan = connection.execute(
                "SELECT status FROM scan_runs WHERE id = %s FOR UPDATE",
                (scan_uuid,),
            ).fetchone()
            if scan is None:
                raise RegistryNotFoundError(f"scan not found: {scan_id}")
            if scan[0] != ScanStatus.COMPLETE.value:
                raise ValueError("reconciliation requires a COMPLETE scan")

            changed = int(
                connection.execute(
                    "SELECT reconcile_missing_asset_locations(%s)",
                    (scan_uuid,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, actor, action, target_type, target_id, decision, details
                )
                VALUES (%s, %s, 'asset_location.reconcile', 'scan_run', %s,
                        'recorded', %s::jsonb)
                """,
                (
                    uuid4(),
                    actor.strip(),
                    str(scan_uuid),
                    json.dumps(
                        {"availability_events": changed, "scan_id": str(scan_uuid)}
                    ),
                ),
            )
            return changed

    def fail_scan(self, scan_id: str, error_summary: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE scan_runs
                   SET status = 'failed', finished_at = now(), error_summary = %s
                 WHERE id = %s AND status = 'running'
                """,
                (error_summary[:1000], self._uuid(scan_id)),
            )
