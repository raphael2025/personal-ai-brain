"""Built-in worker handlers for the initial text extraction pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from personal_ai_brain.extractors.models import ExtractionRequest
from personal_ai_brain.extractors.text import ExtractionError, TextMarkdownExtractor
from personal_ai_brain.ingestion.artifacts import (
    ArtifactConflictError,
    PostgresArtifactRepository,
)
from personal_ai_brain.ingestion.models import JobLease, PermanentJobError
from personal_ai_brain.workers.source_access import (
    AuthorizedSourceReader,
    SourceAccessDeniedError,
    SourceContentMismatchError,
)


class ArtifactPublisher(Protocol):
    def publish(self, lease, artifact, *, config_digest: str) -> str: ...


def text_extraction_config_digest(
    extractor: TextMarkdownExtractor | None = None,
) -> str:
    """Return the canonical config digest used by enqueue and worker execution."""
    selected = extractor or TextMarkdownExtractor()
    config = {
        "extractor_name": selected.MANIFEST.name,
        "extractor_version": selected.MANIFEST.semantic_version,
        "output_schema_version": selected.MANIFEST.output_schema_version,
        "max_input_bytes": selected.MANIFEST.max_input_bytes,
        "network_required": selected.MANIFEST.network_required,
        "media_types": list(selected.MANIFEST.media_types),
        "extensions": list(selected.MANIFEST.extensions),
        "permissions": list(selected.MANIFEST.permissions),
    }
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TextExtractionHandler:
    """Read one authorized immutable source version, extract, and publish under lease."""

    def __init__(
        self,
        source_reader: AuthorizedSourceReader,
        artifact_repository: ArtifactPublisher,
        extractor: TextMarkdownExtractor | None = None,
    ) -> None:
        self.source_reader = source_reader
        self.artifact_repository = artifact_repository
        self.extractor = extractor or TextMarkdownExtractor()

    def __call__(self, lease: JobLease) -> None:
        if lease.config_digest != text_extraction_config_digest(self.extractor):
            raise PermanentJobError("ExtractorConfigMismatch")
        try:
            source = self.source_reader.read_for_lease(lease)
        except (SourceAccessDeniedError, SourceContentMismatchError) as exc:
            raise PermanentJobError(type(exc).__name__) from exc

        if not self.extractor.supports(
            source.reference.relative_path, source.reference.media_type
        ):
            raise PermanentJobError("UnsupportedSourceType")

        request = ExtractionRequest(
            asset_version_id=lease.asset_version_id,
            source_sha256=source.reference.sha256,
            relative_path=source.reference.relative_path,
            media_type=source.reference.media_type,
            source_bytes=source.content,
        )
        try:
            artifact = self.extractor.extract(request)
        except ExtractionError as exc:
            raise PermanentJobError(type(exc).__name__) from exc

        try:
            self.artifact_repository.publish(
                lease, artifact, config_digest=lease.config_digest
            )
        except ArtifactConflictError as exc:
            raise PermanentJobError(type(exc).__name__) from exc
