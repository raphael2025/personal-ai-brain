"""Persistence-agnostic domain models for storage roots and asset locations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class StorageKind(StrEnum):
    """Logical kind of a configured storage source."""

    LOCAL = "local"
    NETWORK = "network"
    REMOVABLE = "removable"


class LocationAvailability(StrEnum):
    """Observed availability; absence is only inferred after a complete scan."""

    AVAILABLE = "available"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    EXCLUDED = "excluded"


def _validate_storage_uri(uri: str, kind: StorageKind) -> str:
    if not isinstance(uri, str) or not uri or uri != uri.strip():
        raise ValueError("uri must be a non-empty, trimmed URI")
    # urllib.parse.urlsplit strips some ASCII control characters. Validate the
    # original value first so the checked representation is exactly what we store.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in uri):
        raise ValueError("uri must not contain ASCII control characters")
    try:
        parsed = urlsplit(uri)
        # Accessing .port performs urllib's numeric/range validation.
        port = parsed.port
    except ValueError as exc:
        raise ValueError("uri is malformed") from exc

    if parsed.scheme not in {"file", "smb", "nfs"}:
        raise ValueError("uri scheme must be file, smb, or nfs")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials must not be embedded in storage URIs")
    if parsed.query or parsed.fragment:
        raise ValueError("storage URI must not contain a query or fragment")

    if parsed.scheme == "file":
        if kind is StorageKind.NETWORK:
            raise ValueError("network storage must use smb or nfs URI")
        if not parsed.path.startswith("/"):
            raise ValueError("file URI must contain an absolute path")
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("remote file URI authorities are not supported; use smb or nfs")
    else:
        if kind is not StorageKind.NETWORK:
            raise ValueError("smb and nfs URIs require network storage kind")
        if not parsed.hostname or not parsed.path.startswith("/"):
            raise ValueError("network URI must include a host and absolute share/export path")
        if parsed.scheme == "smb" and not parsed.path.lstrip("/").split("/", 1)[0]:
            raise ValueError("smb URI must include a share component")
        if port == 0:
            raise ValueError("network URI port must be between 1 and 65535")
    return uri


@dataclass(frozen=True, slots=True)
class StorageRoot:
    """A logical storage source, independent of a machine-specific mount path."""

    root_id: str
    display_name: str
    uri: str
    kind: StorageKind
    enabled: bool = True
    follow_symlinks: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.root_id, str) or not self.root_id.strip():
            raise ValueError("root_id must be a non-empty string")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name must be a non-empty string")
        if not isinstance(self.kind, StorageKind):
            raise ValueError("kind must be a StorageKind")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if type(self.follow_symlinks) is not bool:
            raise ValueError("follow_symlinks must be a boolean")
        object.__setattr__(self, "uri", _validate_storage_uri(self.uri, self.kind))
        if self.follow_symlinks:
            raise ValueError("following symlinks is not supported by the initial scanner")


@dataclass(frozen=True, slots=True)
class AssetLocation:
    """A path for an asset relative to one logical storage root."""

    root_id: str
    relative_path: str
    availability: LocationAvailability = LocationAvailability.AVAILABLE

    def __post_init__(self) -> None:
        if not isinstance(self.root_id, str) or not self.root_id.strip():
            raise ValueError("root_id must be a non-empty string")
        if not isinstance(self.relative_path, str) or not self.relative_path.strip():
            raise ValueError("relative_path must be a non-empty string")
        if not isinstance(self.availability, LocationAvailability):
            raise ValueError("availability must be a LocationAvailability")

        normalized = self.relative_path.replace("\\", "/")
        if "\x00" in normalized:
            raise ValueError("relative_path must not contain NUL")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            raise ValueError("relative_path must not be absolute")
        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("relative_path must not contain empty, dot, or parent segments")
        object.__setattr__(self, "relative_path", "/".join(parts))
