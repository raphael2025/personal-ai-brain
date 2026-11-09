"""PostgreSQL adapter for the Asset Registry.

The domain layer stays DB-driver agnostic. This adapter accepts a DB-API connection
factory, allowing tests to inject an existing transaction and applications to load
psycopg only when PostgreSQL persistence is selected.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Protocol
from uuid import UUID, uuid4

from personal_ai_brain.assets.models import StorageKind, StorageRoot
from personal_ai_brain.assets.scanner import ScanObservation, ScanStatus


@dataclass(frozen=True, slots=True)
class StorageRootRecord:
    root: StorageRoot
    path_case_sensitive: bool | None
    path_normalizer_version: str


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

    def fail_scan(self, scan_id: str, error_summary: str) -> None: ...


class RegistryNotFoundError(LookupError):
    """A requested registry object does not exist."""


class PathNormalizerMigrationRequired(RuntimeError):
    """Active location keys need explicit migration before scanning can reconcile."""


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

    def start_scan(self, root_id: str, *, scanner_version: str) -> str:
        scan_id = uuid4()
        root_uuid = self._uuid(root_id)
        with self._connection() as connection:
            root = connection.execute(
                """
                SELECT path_normalizer_version, enabled
                  FROM storage_roots
                 WHERE id = %s
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
        normalized = relative_path.replace("\\", "/")
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
                SELECT storage_root_id, path_normalizer_version
                  FROM scan_runs
                 WHERE id = %s AND status = 'running'
                """,
                (scan_uuid,),
            ).fetchone()
            if scan is None:
                raise RegistryNotFoundError(f"running scan not found: {scan_id}")
            root_id, normalizer_version = scan

            for prepared in observations:
                observation = prepared.observation
                path_key = self._normalized_key(
                    observation.relative_path, normalizer_version
                )
                version_id = None

                if observation.kind is EntryKind.FILE and prepared.sha256 is not None:
                    existing_location = connection.execute(
                        """
                        SELECT id, asset_id, current_version_id
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
                        location_id, asset_id, _current_version_id = existing_location

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
                        location_id, asset_id, current_version_id = existing_location
                        if (
                            current_version_id != version_id
                            or observation.relative_path != existing_location[0]
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

            if status is ScanStatus.COMPLETE:
                changed = connection.execute(
                    "SELECT reconcile_missing_asset_locations(%s)", (scan_uuid,)
                ).fetchone()[0]
                return int(changed)
        return 0

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
