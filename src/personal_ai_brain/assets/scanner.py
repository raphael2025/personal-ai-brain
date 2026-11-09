"""Read-only directory discovery with explicit incomplete-scan semantics."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class ScanStatus(StrEnum):
    """Overall result of a directory discovery pass."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class EntryKind(StrEnum):
    """Filesystem entry type, determined without following symlinks."""

    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ScanObservation:
    """Metadata observed for one entry, relative to the configured root."""

    relative_path: str
    kind: EntryKind
    size_bytes: int
    modified_time_ns: int


@dataclass(frozen=True, slots=True)
class ScanIssue:
    """A discovery error without leaking absolute host paths."""

    relative_path: str
    operation: str
    error_type: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Immutable result of a read-only scan."""

    root: Path
    status: ScanStatus
    observations: tuple[ScanObservation, ...]
    issues: tuple[ScanIssue, ...]
    started_at: datetime
    finished_at: datetime


def scan_directory(root: Path) -> ScanResult:
    """Discover entries under *root* without following symlinks or writing files.

    A missing/inaccessible root is FAILED. Errors below an accessible root make
    the result PARTIAL. Callers must only infer absence after a COMPLETE scan;
    PARTIAL and FAILED scans must never be used to mark prior locations missing.
    """
    root = Path(root)
    started_at = datetime.now(UTC)
    observations: list[ScanObservation] = []
    issues: list[ScanIssue] = []

    try:
        root_stat = root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise NotADirectoryError("scan root must be a real directory, not a symlink")
        pending = [root]
    except OSError as exc:
        issues.append(
            ScanIssue(relative_path=".", operation="open_root", error_type=type(exc).__name__)
        )
        return ScanResult(
            root=root,
            status=ScanStatus.FAILED,
            observations=(),
            issues=tuple(issues),
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                        if entry.is_symlink():
                            kind = EntryKind.SYMLINK
                        elif stat.S_ISDIR(entry_stat.st_mode):
                            kind = EntryKind.DIRECTORY
                            pending.append(path)
                        elif stat.S_ISREG(entry_stat.st_mode):
                            kind = EntryKind.FILE
                        else:
                            kind = EntryKind.OTHER
                        observations.append(
                            ScanObservation(
                                relative_path=relative,
                                kind=kind,
                                size_bytes=entry_stat.st_size,
                                modified_time_ns=entry_stat.st_mtime_ns,
                            )
                        )
                    except OSError as exc:
                        issues.append(
                            ScanIssue(
                                relative_path=relative,
                                operation="stat_entry",
                                error_type=type(exc).__name__,
                            )
                        )
        except OSError as exc:
            relative = "." if directory == root else directory.relative_to(root).as_posix()
            issues.append(
                ScanIssue(
                    relative_path=relative,
                    operation="read_directory",
                    error_type=type(exc).__name__,
                )
            )

    observations.sort(key=lambda item: item.relative_path.casefold())
    issues.sort(key=lambda item: (item.relative_path.casefold(), item.operation))
    status = ScanStatus.PARTIAL if issues else ScanStatus.COMPLETE
    return ScanResult(
        root=root,
        status=status,
        observations=tuple(observations),
        issues=tuple(issues),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
