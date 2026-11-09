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
    if not uri or uri != uri.strip():
        raise ValueError("uri must be a non-empty, trimmed URI")
    parsed = urlsplit(uri)
    if parsed.scheme not in {"file", "smb", "nfs"}:
        raise ValueError("uri scheme must be file, smb, or nfs")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials must not be embedded in storage URIs")
    if parsed.query or parsed.fragment:
        raise ValueError("storage URI must not contain a query or fragment")
    if parsed.scheme == "file":
        if kind is StorageKind.NETWORK:
            raise ValueError("network storage must use smb or nfs URI")
        if not parsed.path:
            raise ValueError("file URI must include a path")
    elif kind is not StorageKind.NETWORK:
        raise ValueError("smb and nfs URIs require network storage kind")
    elif not parsed.hostname or not parsed.path:
        raise ValueError("network URI must include a host and share/export path")
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
        if not self.root_id or not self.root_id.strip():
            raise ValueError("root_id must be non-empty")
        if not self.display_name or not self.display_name.strip():
            raise ValueError("display_name must be non-empty")
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
        if not self.root_id or not self.root_id.strip():
            raise ValueError("root_id must be non-empty")
        if not self.relative_path or not self.relative_path.strip():
            raise ValueError("relative_path must be non-empty")
        normalized = self.relative_path.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            raise ValueError("relative_path must not be absolute")
        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("relative_path must not contain empty, dot, or parent segments")
        object.__setattr__(self, "relative_path", "/".join(parts))
