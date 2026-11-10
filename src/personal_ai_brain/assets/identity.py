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

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
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



def identify_file_at(
    root: Path,
    relative_path: str,
    *,
    expected_size: int | None = None,
    expected_mtime_ns: int | None = None,
    chunk_size: int = 1024 * 1024,
) -> FileIdentity:
    """Hash a file beneath an explicitly opened root using descriptor-relative access.

    Every directory component and the final file are opened with O_NOFOLLOW.
    The function fails closed when the platform lacks the required dir_fd
    primitives. The expected metadata ties the hash to the discovery snapshot;
    the open file descriptor is then checked before and after reading.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("relative_path must be a non-empty string")
    parts = relative_path.split("/")
    if relative_path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative_path must be root-relative without traversal segments")
    if (
        os.open not in os.supports_dir_fd
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
    ):
        raise RuntimeError("descriptor-relative file hashing is unsupported on this platform")

    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    opened_directories: list[int] = []
    root_fd: int | None = None
    file_fd: int | None = None
    try:
        root_fd = os.open(Path(root), directory_flags)
        parent_fd = root_fd
        for component in parts[:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            opened_directories.append(child_fd)
            parent_fd = child_fd

        file_fd = os.open(parts[-1], file_flags, dir_fd=parent_fd)
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("target is not a regular file")
            if expected_size is not None and before.st_size != expected_size:
                raise FileChangedDuringReadError(
                    f"File size changed after discovery: {relative_path}"
                )
            if expected_mtime_ns is not None and before.st_mtime_ns != expected_mtime_ns:
                raise FileChangedDuringReadError(
                    f"File timestamp changed after discovery: {relative_path}"
                )

            digest = hashlib.sha256()
            bytes_read = 0
            while chunk := stream.read(chunk_size):
                digest.update(chunk)
                bytes_read += len(chunk)
            after = os.fstat(stream.fileno())

            if (
                _file_signature(before) != _file_signature(after)
                or bytes_read != after.st_size
            ):
                raise FileChangedDuringReadError(
                    f"File changed while hashing: {relative_path}"
                )

        return FileIdentity(sha256=digest.hexdigest(), size_bytes=bytes_read)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
        if root_fd is not None:
            os.close(root_fd)


def read_file_at(
    root: Path,
    relative_path: str,
    *,
    expected_size: int | None = None,
    expected_mtime_ns: int | None = None,
    max_bytes: int = 16 * 1024 * 1024,
    chunk_size: int = 256 * 1024,
) -> bytes:
    """Read a bounded file beneath an explicitly opened root.

    Directory components and the final file are opened descriptor-relative
    with no-follow semantics. The open file descriptor is checked before and
    after reading, and the returned bytes are tied to the caller's discovery
    size/mtime snapshot when those values are supplied.
    """
    if max_bytes <= 0 or chunk_size <= 0:
        raise ValueError("max_bytes and chunk_size must be greater than zero")
    if expected_size is not None and expected_size < 0:
        raise ValueError("expected_size must be non-negative")
    if expected_size is not None and expected_size > max_bytes:
        raise ValueError("source exceeds the configured read limit")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("relative_path must be a non-empty string")
    parts = relative_path.split("/")
    if (
        relative_path.startswith("/")
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("relative_path must be root-relative without traversal segments")
    if (
        os.open not in os.supports_dir_fd
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
    ):
        raise RuntimeError("descriptor-relative source reading is unsupported on this platform")

    root_path = Path(root)
    if not root_path.is_absolute():
        raise ValueError("root must be an absolute path")

    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    opened_directories: list[int] = []
    root_fd: int | None = None
    file_fd: int | None = None
    try:
        root_fd = os.open(root_path, directory_flags)
        parent_fd = root_fd
        for component in parts[:-1]:
            child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            opened_directories.append(child_fd)
            parent_fd = child_fd

        file_fd = os.open(parts[-1], file_flags, dir_fd=parent_fd)
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("source target is not a regular file")
            if before.st_size > max_bytes:
                raise ValueError("source exceeds the configured read limit")
            if expected_size is not None and before.st_size != expected_size:
                raise FileChangedDuringReadError(
                    f"File size changed after discovery: {relative_path}"
                )
            if expected_mtime_ns is not None and before.st_mtime_ns != expected_mtime_ns:
                raise FileChangedDuringReadError(
                    f"File timestamp changed after discovery: {relative_path}"
                )

            output = bytearray()
            while chunk := stream.read(min(chunk_size, max_bytes + 1 - len(output))):
                output.extend(chunk)
                if len(output) > max_bytes:
                    raise ValueError("source exceeds the configured read limit")

            after = os.fstat(stream.fileno())
            if (
                _file_signature(before) != _file_signature(after)
                or len(output) != after.st_size
            ):
                raise FileChangedDuringReadError(
                    f"File changed while reading: {relative_path}"
                )
            return bytes(output)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
        if root_fd is not None:
            os.close(root_fd)
