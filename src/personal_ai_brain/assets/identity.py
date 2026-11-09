"""Content-based file identity primitives.

These functions only read source files. They never modify, move, or delete them.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


class FileChangedDuringReadError(RuntimeError):
    """Raised when a file changes while its content hash is being calculated."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Stable identity for one observed file content version."""

    sha256: str
    size_bytes: int

    @property
    def asset_version_id(self) -> str:
        """Return a deterministic identifier for this exact content version."""
        return f"sha256:{self.sha256}:{self.size_bytes}"


def _file_signature(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return fields useful for detecting replacement or mutation."""
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def identify_file(path: Path, *, chunk_size: int = 1024 * 1024) -> FileIdentity:
    """Calculate a SHA-256 content identity using bounded memory.

    Hashing is performed through one open file descriptor. Symlinks and
    non-regular files are rejected. O_NOFOLLOW is used where the platform
    provides it; descriptor and path metadata are compared to detect
    replacement between inspection and opening, and during the read.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    path = Path(path)
    before_path = path.lstat()
    if stat.S_ISLNK(before_path.st_mode) or not stat.S_ISREG(before_path.st_mode):
        raise ValueError(f"Not a regular non-symlink file: {path}")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, flags)
    with os.fdopen(file_descriptor, "rb") as stream:
        before_fd = os.fstat(stream.fileno())
        if not stat.S_ISREG(before_fd.st_mode):
            raise ValueError(f"Not a regular file: {path}")
        if _file_signature(before_path) != _file_signature(before_fd):
            raise FileChangedDuringReadError(f"File changed before hashing: {path}")

        digest = hashlib.sha256()
        bytes_read = 0
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            bytes_read += len(chunk)

        after_fd = os.fstat(stream.fileno())

    try:
        after_path = path.lstat()
    except FileNotFoundError as exc:
        raise FileChangedDuringReadError(f"File disappeared while hashing: {path}") from exc

    if (
        _file_signature(before_fd) != _file_signature(after_fd)
        or _file_signature(after_fd) != _file_signature(after_path)
        or bytes_read != after_fd.st_size
        or not stat.S_ISREG(after_path.st_mode)
    ):
        raise FileChangedDuringReadError(f"File changed while hashing: {path}")

    return FileIdentity(sha256=digest.hexdigest(), size_bytes=bytes_read)
