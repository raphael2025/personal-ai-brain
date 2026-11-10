"""Read-only operator queries for the PostgreSQL Asset Registry."""

from __future__ import annotations

from typing import Any

from personal_ai_brain.assets.repository import (
    PostgresAssetRegistryRepository,
    RegistryNotFoundError,
)


class PostgresAssetRegistryOperations(PostgresAssetRegistryRepository):
    """Adds bounded, read-only inspection queries to the registry adapter."""

    @staticmethod
    def _limit(limit: int, *, maximum: int = 500) -> int:
        if type(limit) is not int or not 1 <= limit <= maximum:
            raise ValueError(f"limit must be between 1 and {maximum}")
        return limit

    def list_scans(self, *, root_id: str | None = None, limit: int = 50) -> list[tuple[Any, ...]]:
        limit = self._limit(limit)
        params: tuple[Any, ...] = ()
        where = ""
        if root_id is not None:
            where = "WHERE storage_root_id = %s"
            params = (self._uuid(root_id),)
        with self._connection() as connection:
            return connection.execute(
                f"""
                SELECT id, storage_root_id, status, scanner_version,
                       path_normalizer_version, started_at, finished_at,
                       error_summary
                  FROM scan_runs
                  {where}
                 ORDER BY started_at DESC, id DESC
                 LIMIT %s
                """,
                (*params, limit),
            ).fetchall()

    def list_assets(
        self, *, root_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[tuple[Any, ...]]:
        limit = self._limit(limit)
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        params: tuple[Any, ...] = ()
        where = ""
        if root_id is not None:
            where = "WHERE l.storage_root_id = %s"
            params = (self._uuid(root_id),)
        with self._connection() as connection:
            return connection.execute(
                f"""
                SELECT a.id, l.storage_root_id, l.relative_path, l.availability,
                       v.sha256, v.size_bytes, l.last_seen_at
                  FROM assets AS a
                  JOIN asset_locations AS l ON l.asset_id = a.id
                  LEFT JOIN asset_versions AS v ON v.id = l.current_version_id
                  {where}
                 ORDER BY l.last_seen_at DESC, a.id, l.relative_path
                 LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            ).fetchall()

    def inspect_asset(self, asset_id: str) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        asset_uuid = self._uuid(asset_id)
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM assets WHERE id = %s", (asset_uuid,)
            ).fetchone()
            if exists is None:
                raise RegistryNotFoundError(f"asset not found: {asset_id}")
            versions = connection.execute(
                """
                SELECT id, sha256, size_bytes, detected_mime_type,
                       observed_modified_at, created_at
                  FROM asset_versions
                 WHERE asset_id = %s
                 ORDER BY created_at DESC, id
                """,
                (asset_uuid,),
            ).fetchall()
            locations = connection.execute(
                """
                SELECT id, storage_root_id, relative_path, availability,
                       path_normalizer_version, first_seen_at, last_seen_at,
                       valid_from, valid_to, current_version_id
                  FROM asset_locations
                 WHERE asset_id = %s
                 ORDER BY valid_to NULLS FIRST, first_seen_at DESC, id
                """,
                (asset_uuid,),
            ).fetchall()
        return versions, locations

    def preview_reconciliation(self, scan_id: str) -> tuple[tuple[Any, ...], list[tuple[Any, ...]]]:
        scan_uuid = self._uuid(scan_id)
        with self._connection() as connection:
            scan = connection.execute(
                """
                SELECT id, storage_root_id, status, path_normalizer_version, finished_at
                  FROM scan_runs WHERE id = %s
                """,
                (scan_uuid,),
            ).fetchone()
            if scan is None:
                raise RegistryNotFoundError(f"scan not found: {scan_id}")
            if scan[2] != "complete" or scan[4] is None:
                raise ValueError("reconciliation preview requires a COMPLETE scan")
            mismatch = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM asset_locations
                     WHERE storage_root_id = %s AND valid_to IS NULL
                       AND path_normalizer_version <> %s
                )
                """,
                (scan[1], scan[3]),
            ).fetchone()[0]
            if mismatch:
                raise ValueError("path normalizer version mismatch; migrate before reconciliation")
            candidates = connection.execute(
                """
                SELECT l.id, l.asset_id, l.relative_path, l.availability,
                       l.last_seen_at
                  FROM asset_locations AS l
                 WHERE l.storage_root_id = %s
                   AND l.valid_to IS NULL
                   AND l.availability IN ('available', 'excluded')
                   AND NOT EXISTS (
                       SELECT 1 FROM scan_observations AS o
                        WHERE o.scan_run_id = %s
                          AND o.normalized_path_key = l.normalized_path_key
                          AND o.path_normalizer_version = l.path_normalizer_version
                          AND o.entry_kind = 'file'
                   )
                 ORDER BY l.relative_path, l.id
                """,
                (scan[1], scan_uuid),
            ).fetchall()
        return scan, candidates
