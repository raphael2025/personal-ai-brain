"""Persistence-agnostic extraction contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExtractorManifest:
    name: str
    semantic_version: str
    output_schema_version: str
    media_types: tuple[str, ...]
    extensions: tuple[str, ...]
    max_input_bytes: int
    network_required: bool = False
    permissions: tuple[str, ...] = ("read_source_version",)

    def __post_init__(self) -> None:
        for field_name in ("name", "semantic_version", "output_schema_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if type(self.max_input_bytes) is not int or self.max_input_bytes <= 0:
            raise ValueError("max_input_bytes must be a positive integer")
        if self.network_required:
            raise ValueError("initial extractors must not require network access")


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    asset_version_id: str
    source_sha256: str
    relative_path: str
    media_type: str | None
    source_bytes: bytes

    def __post_init__(self) -> None:
        if not self.asset_version_id or not self.asset_version_id.strip():
            raise ValueError("asset_version_id must be non-empty")
        if len(self.source_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_sha256
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.relative_path, str) or not self.relative_path:
            raise ValueError("relative_path must be non-empty")
        if not isinstance(self.source_bytes, bytes):
            raise ValueError("source_bytes must be bytes")


@dataclass(frozen=True, slots=True)
class ExtractionArtifact:
    asset_version_id: str
    source_sha256: str
    extractor_name: str
    extractor_version: str
    output_schema_version: str
    artifact_type: str
    payload: dict[str, Any]
    content_sha256: str
    size_bytes: int
