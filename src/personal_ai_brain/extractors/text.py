"""Deterministic, bounded UTF-8 text and Markdown extraction."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

from personal_ai_brain.extractors.models import (
    ExtractionArtifact,
    ExtractionRequest,
    ExtractorManifest,
)


class ExtractionError(ValueError):
    """The source cannot be safely handled by the selected extractor."""


class SourceVersionMismatchError(ExtractionError):
    """The supplied bytes do not match the immutable source-version digest."""


class TextMarkdownExtractor:
    """Extract UTF-8 text without modifying or normalizing the source content."""

    MANIFEST = ExtractorManifest(
        name="text-markdown",
        semantic_version="1.0.0",
        output_schema_version="1",
        media_types=(
            "text/plain",
            "text/markdown",
            "text/x-markdown",
            "text/csv",
            "application/json",
            "application/yaml",
            "application/toml",
        ),
        extensions=(
            ".txt", ".md", ".markdown", ".rst", ".csv", ".json",
            ".yaml", ".yml", ".toml", ".py", ".js", ".ts", ".tsx",
            ".jsx", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".hpp",
            ".sql", ".sh", ".bash", ".ps1", ".html", ".css", ".xml",
        ),
        max_input_bytes=16 * 1024 * 1024,
    )

    def supports(self, relative_path: str, media_type: str | None) -> bool:
        suffix = PurePosixPath(relative_path).suffix.casefold()
        normalized_media_type = (media_type or "").split(";", 1)[0].strip().casefold()
        return (
            suffix in self.MANIFEST.extensions
            or normalized_media_type in self.MANIFEST.media_types
        )

    def extract(self, request: ExtractionRequest) -> ExtractionArtifact:
        if len(request.source_bytes) > self.MANIFEST.max_input_bytes:
            raise ExtractionError("source exceeds the configured 16 MiB limit")
        actual_source_sha256 = hashlib.sha256(request.source_bytes).hexdigest()
        if actual_source_sha256 != request.source_sha256:
            raise SourceVersionMismatchError(
                "source bytes do not match the requested immutable asset version"
            )
        if b"\x00" in request.source_bytes:
            raise ExtractionError("NUL bytes are not accepted by the text extractor")

        try:
            text = request.source_bytes.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ExtractionError("source is not valid UTF-8") from exc

        encoded = text.encode("utf-8")
        content_sha256 = hashlib.sha256(encoded).hexdigest()
        suffix = PurePosixPath(request.relative_path).suffix.casefold()
        payload = {
            "text": text,
            "format": suffix.lstrip(".") or "text",
            "encoding": "utf-8",
            "line_count": text.count("\n") + (1 if text else 0),
            "character_count": len(text),
        }
        return ExtractionArtifact(
            asset_version_id=request.asset_version_id,
            source_sha256=request.source_sha256,
            extractor_name=self.MANIFEST.name,
            extractor_version=self.MANIFEST.semantic_version,
            output_schema_version=self.MANIFEST.output_schema_version,
            artifact_type="extracted_text",
            payload=payload,
            content_sha256=content_sha256,
            size_bytes=len(encoded),
        )
