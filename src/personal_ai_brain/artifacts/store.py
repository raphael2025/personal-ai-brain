"""Atomic content-addressed artifact storage.

The store writes only derived artifacts beneath an explicitly configured root.
It never accepts caller-provided relative paths; object names are SHA-256 digests.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class ArtifactIntegrityError(RuntimeError):
    """An existing content-addressed object does not match its key."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    uri: str
    sha256: str
    size_bytes: int


class LocalArtifactStore:
    """A bounded, no-follow content-addressed store for derived bytes."""

    def __init__(self, root: Path, *, max_object_bytes: int = 64 * 1024 * 1024) -> None:
        if type(max_object_bytes) is not int or max_object_bytes <= 0:
            raise ValueError("max_object_bytes must be a positive integer")
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ValueError("artifact root must be an absolute path")
        self.max_object_bytes = max_object_bytes

    @staticmethod
    def _directory_flags() -> int:
        if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeError("no-follow artifact storage is unsupported on this platform")
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)

    def _open_root(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return os.open(self.root, self._directory_flags())

    @staticmethod
    def _open_or_create_dir(parent_fd: int, name: str) -> int:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(name, LocalArtifactStore._directory_flags(), dir_fd=parent_fd)

    @staticmethod
    def _write_all(fd: int, content: bytes) -> None:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while storing artifact")
            view = view[written:]

    @staticmethod
    def _read_object(directory_fd: int, name: str, *, max_bytes: int) -> bytes:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(name, flags, dir_fd=directory_fd)
        try:
            metadata = os.fstat(fd)
            if not os.path.stat.S_ISREG(metadata.st_mode):
                raise ArtifactIntegrityError("artifact object is not a regular file")
            if metadata.st_size > max_bytes:
                raise ArtifactIntegrityError("artifact object exceeds read limit")
            chunks = bytearray()
            while chunk := os.read(fd, min(256 * 1024, max_bytes + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    raise ArtifactIntegrityError("artifact object exceeds read limit")
            if len(chunks) != metadata.st_size:
                raise ArtifactIntegrityError("artifact object changed while reading")
            return bytes(chunks)
        finally:
            os.close(fd)

    def put(self, content: bytes) -> StoredArtifact:
        if not isinstance(content, bytes):
            raise ValueError("artifact content must be bytes")
        if len(content) > self.max_object_bytes:
            raise ValueError("artifact exceeds configured storage limit")
        digest = hashlib.sha256(content).hexdigest()
        prefix = digest[:2]
        uri = f"artifact://sha256/{prefix}/{digest}"

        root_fd = self._open_root()
        sha_fd = prefix_fd = temp_fd = None
        temp_name = f".{digest}.{uuid4().hex}.tmp"
        try:
            sha_fd = self._open_or_create_dir(root_fd, "sha256")
            prefix_fd = self._open_or_create_dir(sha_fd, prefix)
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            temp_fd = os.open(temp_name, flags, 0o600, dir_fd=prefix_fd)
            self._write_all(temp_fd, content)
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None

            try:
                if os.link not in os.supports_dir_fd:
                    raise RuntimeError("atomic descriptor-relative linking is unsupported")
                os.link(
                    temp_name,
                    digest,
                    src_dir_fd=prefix_fd,
                    dst_dir_fd=prefix_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                existing = self._read_object(
                    prefix_fd, digest, max_bytes=self.max_object_bytes
                )
                if hashlib.sha256(existing).hexdigest() != digest or existing != content:
                    raise ArtifactIntegrityError(
                        "existing artifact object does not match its content address"
                    )
            os.unlink(temp_name, dir_fd=prefix_fd)
            os.fsync(prefix_fd)
            return StoredArtifact(uri=uri, sha256=digest, size_bytes=len(content))
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if prefix_fd is not None:
                try:
                    os.unlink(temp_name, dir_fd=prefix_fd)
                except FileNotFoundError:
                    pass
                os.close(prefix_fd)
            if sha_fd is not None:
                os.close(sha_fd)
            os.close(root_fd)

    def get(self, uri: str) -> bytes:
        match = re.fullmatch(r"artifact://sha256/([0-9a-f]{2})/([0-9a-f]{64})", uri or "")
        if match is None or match.group(1) != match.group(2)[:2]:
            raise ValueError("artifact URI is not a canonical SHA-256 object URI")
        prefix, digest = match.groups()

        root_fd = self._open_root()
        sha_fd = prefix_fd = None
        try:
            sha_fd = os.open("sha256", self._directory_flags(), dir_fd=root_fd)
            prefix_fd = os.open(prefix, self._directory_flags(), dir_fd=sha_fd)
            content = self._read_object(
                prefix_fd, digest, max_bytes=self.max_object_bytes
            )
            if hashlib.sha256(content).hexdigest() != digest:
                raise ArtifactIntegrityError("artifact checksum does not match its URI")
            return content
        finally:
            if prefix_fd is not None:
                os.close(prefix_fd)
            if sha_fd is not None:
                os.close(sha_fd)
            os.close(root_fd)
