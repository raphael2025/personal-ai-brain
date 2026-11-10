"""Unit tests for the bounded text and Markdown extractor."""

from __future__ import annotations

import hashlib

import pytest

from personal_ai_brain.extractors.models import ExtractionRequest
from personal_ai_brain.extractors.text import (
    ExtractionError,
    SourceVersionMismatchError,
    TextMarkdownExtractor,
)


def request(data: bytes, path: str = "notes/readme.md") -> ExtractionRequest:
    return ExtractionRequest(
        asset_version_id="asset-version-1",
        source_sha256=hashlib.sha256(data).hexdigest(),
        relative_path=path,
        media_type="text/markdown",
        source_bytes=data,
    )


def test_extracts_utf8_markdown_without_rewriting_content():
    source = b"\xef\xbb\xbf# Title\r\n\r\nHello, \xe4\xb8\x96\xe7\x95\x8c!\r\n"
    result = TextMarkdownExtractor().extract(request(source))

    assert result.artifact_type == "extracted_text"
    assert result.payload["text"] == "# Title\r\n\r\nHello, 世界!\r\n"
    assert result.payload["format"] == "md"
    assert result.payload["encoding"] == "utf-8"
    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert result.content_sha256 == hashlib.sha256(
        result.payload["text"].encode("utf-8")
    ).hexdigest()


def test_supports_known_text_extensions_and_media_types():
    extractor = TextMarkdownExtractor()

    assert extractor.supports("src/main.py", None)
    assert extractor.supports("unknown.data", "text/plain; charset=utf-8")
    assert not extractor.supports("archive.bin", "application/octet-stream")


def test_rejects_source_version_mismatch():
    extractor = TextMarkdownExtractor()
    request_with_wrong_hash = ExtractionRequest(
        asset_version_id="asset-version-1",
        source_sha256="0" * 64,
        relative_path="notes/readme.md",
        media_type="text/markdown",
        source_bytes=b"# real content",
    )

    with pytest.raises(SourceVersionMismatchError):
        extractor.extract(request_with_wrong_hash)


@pytest.mark.parametrize("source", [b"\xff\xfe", b"hello\x00world"])
def test_rejects_binary_or_invalid_utf8(source: bytes):
    with pytest.raises(ExtractionError):
        TextMarkdownExtractor().extract(request(source))


def test_rejects_inputs_over_size_limit():
    source = b"x" * (TextMarkdownExtractor.MANIFEST.max_input_bytes + 1)

    with pytest.raises(ExtractionError, match="16 MiB"):
        TextMarkdownExtractor().extract(request(source))


def test_empty_file_has_zero_lines():
    result = TextMarkdownExtractor().extract(request(b""))

    assert result.payload["text"] == ""
    assert result.payload["line_count"] == 0
    assert result.size_bytes == 0
