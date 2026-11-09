"""Application service for safe, read-only Asset Registry scans."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from personal_ai_brain.assets.identity import FileChangedDuringReadError, identify_file_at
from personal_ai_brain.assets.repository import (
    AssetRegistryRepository,
    PreparedObservation,
    StorageRootRecord,
)
from personal_ai_brain.assets.scanner import (
    ScanIssue,
    ScanResult,
    ScanStatus,
    scan_directory,
)


@dataclass(frozen=True, slots=True)
class ScanExecution:
    scan_id: str
    result: ScanResult
    reconciliation_events: int


def _local_path(root: StorageRootRecord, override: Path | None) -> Path:
    if override is not None:
        resolved = Path(override).expanduser()
        if not resolved.is_absolute():
            raise ValueError("mounted path override must be absolute")
        return resolved
    parsed = urlsplit(root.root.uri)
    if parsed.scheme != "file":
        raise ValueError(
            "network roots require an explicit mounted path override for this host"
        )
    if parsed.netloc not in {"", "localhost"}:
        raise ValueError("remote file URI authorities are not supported")
    value = unquote(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", value):
        value = value[1:]
    return Path(value)


class AssetRegistryService:
    """Coordinates root registration and scanner-to-registry transactions."""

    def __init__(
        self,
        repository: AssetRegistryRepository,
        *,
        scanner_version: str = "pab-scanner-v1",
    ) -> None:
        self.repository = repository
        self.scanner_version = scanner_version

    def scan_root(
        self, root_id: str, *, local_path: Path | None = None
    ) -> ScanExecution:
        root = self.repository.get_root(root_id)
        path = _local_path(root, local_path)
        scan_id = self.repository.start_scan(
            root_id, scanner_version=self.scanner_version
        )

        try:
            discovered = scan_directory(path)
            issues = list(discovered.issues)
            prepared: list[PreparedObservation] = []

            for observation in discovered.observations:
                if observation.kind.value != "file":
                    prepared.append(PreparedObservation(observation))
                    continue
                try:
                    identity = identify_file_at(
                        path,
                        observation.relative_path,
                        expected_size=observation.size_bytes,
                        expected_mtime_ns=observation.modified_time_ns,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    issues.append(
                        ScanIssue(
                            relative_path=observation.relative_path,
                            operation="hash_file",
                            error_type=type(exc).__name__,
                        )
                    )
                    prepared.append(PreparedObservation(observation))
                else:
                    prepared.append(
                        PreparedObservation(
                            observation,
                            sha256=identity.sha256,
                            size_bytes=identity.size_bytes,
                        )
                    )

            status = discovered.status
            if issues and status is ScanStatus.COMPLETE:
                status = ScanStatus.PARTIAL
            error_summary = None
            if issues:
                error_summary = "; ".join(
                    f"{issue.operation}:{issue.error_type}" for issue in issues[:20]
                )

            reconciliation_events = self.repository.finish_scan(
                scan_id,
                prepared,
                status=status,
                error_summary=error_summary,
            )
            final_result = ScanResult(
                root=discovered.root,
                status=status,
                observations=discovered.observations,
                issues=tuple(sorted(
                    issues,
                    key=lambda item: (item.relative_path.casefold(), item.operation),
                )),
                started_at=discovered.started_at,
                finished_at=discovered.finished_at,
            )
            return ScanExecution(scan_id, final_result, reconciliation_events)
        except Exception as exc:
            try:
                self.repository.fail_scan(scan_id, type(exc).__name__)
            except Exception:
                # Preserve the original exception; an interrupted DB may also
                # prevent recording the terminal failure.
                pass
            raise
