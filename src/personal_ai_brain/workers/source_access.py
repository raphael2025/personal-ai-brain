"""Root-scoped source authorization and descriptor-relative worker reads."""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID, uuid4

from personal_ai_brain.assets.identity import read_file_at


class SourceAccessDeniedError(PermissionError):
    """The worker has no active grant for the requested source."""


class SourceContentMismatchError(RuntimeError):
    """Bytes read from a source location do not match its immutable asset version."""


@dataclass(frozen=True, slots=True)
class WorkerSourceReference:
    root_id: str
    asset_version_id: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str | None


@dataclass(frozen=True, slots=True)
class SourceContent:
    reference: WorkerSourceReference
    content: bytes


class WorkerSourceAccessRepository(Protocol):
    def resolve_source(
        self,
        *,
        worker_id: str,
        job_id: str,
        lease_generation: int,
        root_id: str,
        asset_version_id: str,
    ) -> WorkerSourceReference: ...


class PostgresWorkerSourceAccessRepository:
    """Database-enforced worker/root grant checks and immutable source resolution."""

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
    def _uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"{field_name} must be a UUID string") from exc

    @staticmethod
    def _actor(value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError("actor must be non-empty and at most 200 characters")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("actor must not contain ASCII control characters")
        return value.strip()

    def grant_root(self, worker_id: str, root_id: str, *, actor: str) -> None:
        worker_uuid = self._uuid(worker_id, "worker_id")
        root_uuid = self._uuid(root_id, "root_id")
        actor = self._actor(actor)
        with self._connection() as connection:
            worker = connection.execute(
                "SELECT enabled FROM workers WHERE id = %s FOR UPDATE",
                (worker_uuid,),
            ).fetchone()
            root = connection.execute(
                "SELECT enabled FROM storage_roots WHERE id = %s FOR UPDATE",
                (root_uuid,),
            ).fetchone()
            if worker is None or root is None:
                raise ValueError("worker or storage root does not exist")
            if not worker[0] or not root[0]:
                raise ValueError("cannot grant access to a disabled worker or storage root")

            connection.execute(
                """
                INSERT INTO worker_root_grants (
                    worker_id, storage_root_id, permission, granted_by,
                    granted_at, revoked_at, revoked_by
                )
                VALUES (%s, %s, 'read_source', %s, now(), NULL, NULL)
                ON CONFLICT (worker_id, storage_root_id, permission)
                DO UPDATE SET granted_by = EXCLUDED.granted_by,
                              granted_at = now(),
                              revoked_at = NULL,
                              revoked_by = NULL
                """,
                (worker_uuid, root_uuid, actor),
            )
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, actor, action, target_type, target_id, decision, details
                )
                VALUES (%s, %s, 'worker_root.grant', 'worker_root_grant',
                        %s, 'recorded', %s::jsonb)
                """,
                (
                    uuid4(),
                    actor,
                    str(root_uuid),
                    json.dumps(
                        {"worker_id": str(worker_uuid), "permission": "read_source"}
                    ),
                ),
            )

    def revoke_root(
        self, worker_id: str, root_id: str, *, actor: str
    ) -> bool:
        worker_uuid = self._uuid(worker_id, "worker_id")
        root_uuid = self._uuid(root_id, "root_id")
        actor = self._actor(actor)
        with self._connection() as connection:
            revoked = connection.execute(
                """
                UPDATE worker_root_grants
                   SET revoked_at = now(), revoked_by = %s
                 WHERE worker_id = %s AND storage_root_id = %s
                   AND permission = 'read_source' AND revoked_at IS NULL
                RETURNING worker_id
                """,
                (actor, worker_uuid, root_uuid),
            ).fetchone()
            if revoked is None:
                return False
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, actor, action, target_type, target_id, decision, details
                )
                VALUES (%s, %s, 'worker_root.revoke', 'worker_root_grant',
                        %s, 'recorded', %s::jsonb)
                """,
                (
                    uuid4(),
                    actor,
                    str(root_uuid),
                    json.dumps(
                        {"worker_id": str(worker_uuid), "permission": "read_source"}
                    ),
                ),
            )
            return True

    def resolve_source(
        self,
        *,
        worker_id: str,
        job_id: str,
        lease_generation: int,
        root_id: str,
        asset_version_id: str,
    ) -> WorkerSourceReference:
        worker_uuid = self._uuid(worker_id, "worker_id")
        job_uuid = self._uuid(job_id, "job_id")
        root_uuid = self._uuid(root_id, "root_id")
        version_uuid = self._uuid(asset_version_id, "asset_version_id")
        if type(lease_generation) is not int or lease_generation <= 0:
            raise ValueError("lease_generation must be a positive integer")
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT l.relative_path, v.sha256, v.size_bytes, v.detected_mime_type
                  FROM workers AS w
                  JOIN processing_jobs AS j
                    ON j.id = %s
                   AND j.asset_version_id = %s
                   AND j.lease_owner_worker_id = w.id
                   AND j.lease_generation = %s
                   AND j.status IN ('leased', 'running')
                   AND j.lease_expires_at > clock_timestamp()
                  JOIN worker_root_grants AS g
                    ON g.worker_id = w.id
                   AND g.storage_root_id = %s
                   AND g.permission = 'read_source'
                   AND g.revoked_at IS NULL
                  JOIN storage_roots AS r
                    ON r.id = g.storage_root_id AND r.enabled = true
                  JOIN asset_locations AS l
                    ON l.storage_root_id = r.id
                   AND l.current_version_id = %s
                   AND l.availability = 'available'
                   AND l.valid_to IS NULL
                  JOIN asset_versions AS v
                    ON v.id = l.current_version_id AND v.asset_id = l.asset_id
                 WHERE w.id = %s AND w.enabled = true
                 ORDER BY l.relative_path, l.id
                 LIMIT 1
                """,
                (job_uuid, version_uuid, lease_generation, root_uuid, version_uuid, worker_uuid),
            ).fetchone()
        if row is None:
            raise SourceAccessDeniedError(
                "worker is not authorized for this source or the source is unavailable"
            )
        return WorkerSourceReference(
            root_id=str(root_uuid),
            asset_version_id=str(version_uuid),
            relative_path=row[0],
            sha256=str(row[1]).strip(),
            size_bytes=row[2],
            media_type=row[3],
        )


@dataclass(frozen=True, slots=True)
class WorkerMountMap:
    worker_id: str
    mounts: Mapping[str, Path]

    def __post_init__(self) -> None:
        try:
            worker_id = str(UUID(self.worker_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("worker_id must be a UUID string") from exc
        if not isinstance(self.mounts, Mapping):
            raise ValueError("mounts must be a mapping")
        normalized: dict[str, Path] = {}
        for root_id, mount_path in self.mounts.items():
            try:
                normalized_root_id = str(UUID(root_id))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("mount keys must be storage-root UUIDs") from exc
            path = Path(mount_path).expanduser()
            if not path.is_absolute():
                raise ValueError("worker mount paths must be absolute")
            if "\x00" in str(path):
                raise ValueError("worker mount paths must not contain NUL")
            if normalized_root_id in normalized:
                raise ValueError("duplicate storage-root mount")
            normalized[normalized_root_id] = path
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "mounts", MappingProxyType(normalized))


def load_worker_mount_map(
    config_path: Path, *, expected_worker_id: str | None = None
) -> WorkerMountMap:
    """Load an explicit worker-local TOML mount map; paths never come from job payloads."""
    raw = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    if (
        set(raw) != {"version", "worker_id", "mounts"}
        or type(raw["version"]) is not int
        or raw["version"] != 1
    ):
        raise ValueError("mount config must contain only version=1, worker_id, and mounts")
    if not isinstance(raw["mounts"], dict):
        raise ValueError("mounts must be a TOML table")
    if any(not isinstance(value, str) for value in raw["mounts"].values()):
        raise ValueError("every mount path must be a string")
    mount_map = WorkerMountMap(raw["worker_id"], raw["mounts"])
    if expected_worker_id is not None and mount_map.worker_id != str(UUID(expected_worker_id)):
        raise ValueError("mount config worker_id does not match the running worker")
    return mount_map


class AuthorizedSourceReader:
    """Resolve source paths only through a database grant and local root mount map."""

    def __init__(
        self,
        repository: WorkerSourceAccessRepository,
        mounts: WorkerMountMap,
        *,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.repository = repository
        self.mounts = mounts
        self.max_bytes = max_bytes

    def read_for_lease(self, lease: Any) -> SourceContent:
        if str(UUID(lease.worker_id)) != self.mounts.worker_id:
            raise SourceAccessDeniedError("worker identity does not match its mount config")
        payload = lease.payload
        if not isinstance(payload, dict) or not isinstance(payload.get("root_id"), str):
            raise ValueError("job payload must contain a storage root_id")
        root_id = str(UUID(payload["root_id"]))
        mount_path = self.mounts.mounts.get(root_id)
        if mount_path is None:
            raise SourceAccessDeniedError("worker has no local mount configured for this root")

        reference = self.repository.resolve_source(
            worker_id=lease.worker_id,
            job_id=lease.job_id,
            lease_generation=lease.generation,
            root_id=root_id,
            asset_version_id=lease.asset_version_id,
        )
        content = read_file_at(
            mount_path,
            reference.relative_path,
            expected_size=reference.size_bytes,
            max_bytes=self.max_bytes,
        )
        digest = hashlib.sha256(content).hexdigest()
        if digest != reference.sha256:
            raise SourceContentMismatchError(
                "read source bytes do not match the immutable asset version"
            )
        return SourceContent(reference=reference, content=content)
