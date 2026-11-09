"""Content-based file identity primitives.

These functions only read source files. They never modify, move, or delete them.
"""

from __future__ import annotations

import hashlib
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


def identify_file(path: Path, *, chunk_size: int = 1024 * 1024) -> FileIdentity:
    """Calculate a SHA-256 content identity using bounded memory.

    The file is stat'ed before and after hashing. If size, modification time, or
    inode changes during the read, the result is rejected rather than recording
    a potentially inconsistent fingerprint.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    path = Path(path)
    before = path.stat()
    if not path.is_file():
        raise ValueError(f"Not a regular file: {path}")

    digest = hashlib.sha256()
    bytes_read = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            bytes_read += len(chunk)

    after = path.stat()
    before_signature = (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None))
    after_signature = (after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None))

    if before_signature != after_signature or bytes_read != after.st_size:
        raise FileChangedDuringReadError(f"File changed while hashing: {path}")

    return FileIdentity(sha256=digest.hexdigest(), size_bytes=bytes_read)
