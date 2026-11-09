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


def _secure_traversal_supported() -> bool:
    """Check for the descriptor-relative primitives required by this scanner."""
    return (
        os.open in os.supports_dir_fd
        and os.scandir in os.supports_fd
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )


def _failed_result(
    root: Path,
    started_at: datetime,
    operation: str,
    error_type: str,
) -> ScanResult:
    return ScanResult(
        root=root,
        status=ScanStatus.FAILED,
        observations=(),
        issues=(
            ScanIssue(relative_path=".", operation=operation, error_type=error_type),
        ),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


def scan_directory(root: Path) -> ScanResult:
    """Discover entries without following symlinks or writing to the source.

    Traversal is descriptor-relative: each child directory is opened relative
    to its already-open parent with O_DIRECTORY|O_NOFOLLOW, then its device and
    inode are compared with the no-follow metadata observed before opening.
    This closes the path-based symlink-swap race for directory descent.

    Platforms lacking these primitives fail closed rather than silently using
    a weaker path-based traversal. This is not a complete sandbox against
    hostile concurrent renames of directories after their descriptors open.
    """
    root = Path(root)
    started_at = datetime.now(UTC)

    if not _secure_traversal_supported():
        return _failed_result(
            root,
            started_at,
            "secure_traversal_unsupported",
            "PlatformCapabilityError",
        )

    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    root_fd: int | None = None
    try:
        root_fd = os.open(root, directory_flags)
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            os.close(root_fd)
            return _failed_result(
                root,
                started_at,
                "open_root",
                "NotADirectoryError",
            )
    except OSError as exc:
        if root_fd is not None:
            os.close(root_fd)
        return _failed_result(root, started_at, "open_root", type(exc).__name__)

    observations: list[ScanObservation] = []
    issues: list[ScanIssue] = []
    pending: list[tuple[int, str]] = [(root_fd, "")]

    try:
        while pending:
            directory_fd, relative_directory = pending.pop()
            try:
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        relative = (
                            f"{relative_directory}/{entry.name}"
                            if relative_directory
                            else entry.name
                        )
                        try:
                            entry_stat = entry.stat(follow_symlinks=False)
                        except OSError as exc:
                            issues.append(
                                ScanIssue(
                                    relative_path=relative,
                                    operation="stat_entry",
                                    error_type=type(exc).__name__,
                                )
                            )
                            continue

                        if stat.S_ISLNK(entry_stat.st_mode):
                            kind = EntryKind.SYMLINK
                        elif stat.S_ISDIR(entry_stat.st_mode):
                            kind = EntryKind.DIRECTORY
                            try:
                                child_fd = os.open(
                                    entry.name,
                                    directory_flags,
                                    dir_fd=directory_fd,
                                )
                                child_stat = os.fstat(child_fd)
                                if (
                                    not stat.S_ISDIR(child_stat.st_mode)
                                    or child_stat.st_dev != entry_stat.st_dev
                                    or child_stat.st_ino != entry_stat.st_ino
                                ):
                                    os.close(child_fd)
                                    issues.append(
                                        ScanIssue(
                                            relative_path=relative,
                                            operation="verify_directory",
                                            error_type="DirectoryChangedDuringScan",
                                        )
                                    )
                                else:
                                    pending.append((child_fd, relative))
                            except OSError as exc:
                                issues.append(
                                    ScanIssue(
                                        relative_path=relative,
                                        operation="open_directory",
                                        error_type=type(exc).__name__,
                                    )
                                )
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
                        relative_path=relative_directory or ".",
                        operation="read_directory",
                        error_type=type(exc).__name__,
                    )
                )
            finally:
                os.close(directory_fd)
    finally:
        for directory_fd, _ in pending:
            try:
                os.close(directory_fd)
            except OSError:
                pass

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
