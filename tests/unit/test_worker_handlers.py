"""Tests for the built-in text extraction worker handler."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_ai_brain.extractors.text import TextMarkdownExtractor
from personal_ai_brain.ingestion.models import JobLease, PermanentJobError
from personal_ai_brain.workers.handlers import (
    TextExtractionHandler,
    text_extraction_config_digest,
)
from personal_ai_brain.workers.source_access import (
    SourceAccessDeniedError,
    SourceContent,
    SourceContentMismatchError,
    WorkerSourceReference,
)


def make_lease(config_digest: str | None = None) -> JobLease:
    return JobLease(
        job_id=str(uuid4()),
        worker_id=str(uuid4()),
        asset_version_id=str(uuid4()),
        task_type="extract_text",
        semantic_version="1.0.0",
        config_digest=config_digest or text_extraction_config_digest(),
        payload={"root_id": str(uuid4())},
        attempt_no=1,
        generation=1,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )


class FakeSourceReader:
    def __init__(self, content: bytes):
        self.content = content
        self.error = None

    def read_for_lease(self, lease):
        if self.error:
            raise self.error
        reference = WorkerSourceReference(
            root_id=lease.payload["root_id"],
            asset_version_id=lease.asset_version_id,
            relative_path="notes.md",
            sha256=hashlib.sha256(self.content).hexdigest(),
            size_bytes=len(self.content),
            media_type="text/markdown",
        )
        return SourceContent(reference=reference, content=self.content)


class FakeArtifactRepository:
    def __init__(self):
        self.calls = []

    def publish(self, lease, artifact, *, config_digest):
        self.calls.append((lease, artifact, config_digest))
        return "artifact-id"


def test_text_handler_reads_extracts_and_publishes():
    content = b"# Notes\nHello"
    reader = FakeSourceReader(content)
    artifacts = FakeArtifactRepository()
    handler = TextExtractionHandler(reader, artifacts)
    lease = make_lease()

    handler(lease)

    assert len(artifacts.calls) == 1
    published_lease, artifact, config_digest = artifacts.calls[0]
    assert published_lease == lease
    assert artifact.payload["text"] == "# Notes\nHello"
    assert artifact.source_sha256 == hashlib.sha256(content).hexdigest()
    assert artifact.asset_version_id == lease.asset_version_id
    assert config_digest == lease.config_digest


@pytest.mark.parametrize(
    "error",
    [SourceAccessDeniedError("denied"), SourceContentMismatchError("mismatch")],
)
def test_source_access_failures_are_permanent(error):
    reader = FakeSourceReader(b"# Notes")
    reader.error = error
    artifacts = FakeArtifactRepository()
    handler = TextExtractionHandler(reader, artifacts)

    with pytest.raises(PermanentJobError):
        handler(make_lease())

    assert artifacts.calls == []


def test_unsupported_source_type_is_permanent():
    artifacts = FakeArtifactRepository()
    lease = make_lease()

    class UnsupportedReader(FakeSourceReader):
        def read_for_lease(self, current_lease):
            result = super().read_for_lease(current_lease)
            return SourceContent(
                reference=WorkerSourceReference(
                    root_id=result.reference.root_id,
                    asset_version_id=result.reference.asset_version_id,
                    relative_path="archive.bin",
                    sha256=result.reference.sha256,
                    size_bytes=result.reference.size_bytes,
                    media_type="application/octet-stream",
                ),
                content=result.content,
            )

    handler = TextExtractionHandler(UnsupportedReader(b"binary"), artifacts)
    with pytest.raises(PermanentJobError, match="UnsupportedSourceType"):
        handler(lease)
    assert artifacts.calls == []


def test_invalid_utf8_is_permanent():
    reader = FakeSourceReader(b"\xff")
    artifacts = FakeArtifactRepository()
    handler = TextExtractionHandler(reader, artifacts)

    with pytest.raises(PermanentJobError):
        handler(make_lease())

    assert artifacts.calls == []


def test_config_digest_mismatch_is_permanent():
    handler = TextExtractionHandler(
        FakeSourceReader(b"# Notes"), FakeArtifactRepository()
    )
    lease = make_lease("d" * 64)

    with pytest.raises(PermanentJobError, match="ExtractorConfigMismatch"):
        handler(lease)


def test_config_digest_is_stable_and_matches_default_extractor():
    assert text_extraction_config_digest() == text_extraction_config_digest(
        TextMarkdownExtractor()
    )
    assert len(text_extraction_config_digest()) == 64
