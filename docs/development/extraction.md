# Extraction Foundation

**Status:** The first bounded UTF-8 text/Markdown extractor is implemented. This is a pure adapter foundation, not yet a complete ingestion pipeline.

## Current adapter

`TextMarkdownExtractor` handles UTF-8 text, Markdown, common structured text formats, and source code when the extension or MIME type is supported.

Properties:
- 16 MiB maximum input size.
- Strict UTF-8 decoding; UTF-8 BOM is accepted and removed from extracted text.
- NUL bytes and invalid UTF-8 are rejected explicitly.
- The source byte digest must match the immutable asset-version SHA-256.
- Source text is not newline-normalized or otherwise rewritten.
- Extractor name, semantic version, output schema version, source version, source digest, output digest, and output size are returned with the payload.
- No network access and no source-file writes.

## Example

    import hashlib
    from personal_ai_brain.extractors.models import ExtractionRequest
    from personal_ai_brain.extractors.text import TextMarkdownExtractor

    source = b"# Personal notes\n"
    request = ExtractionRequest(
        asset_version_id="asset-version-uuid",
        source_sha256=hashlib.sha256(source).hexdigest(),
        relative_path="notes/readme.md",
        media_type="text/markdown",
        source_bytes=source,
    )
    artifact = TextMarkdownExtractor().extract(request)

The adapter requires the caller to supply bytes already read from the exact source version. Source-root authorization and descriptor-relative bounded reads are separate responsibilities.

## Not implemented yet

- Safe source reader integrated with StorageRoot authorization.
- PDF, DOCX, HTML, archive, image, audio, and video extractors.
- Isolated artifact staging, content-addressed storage, checksum revalidation, and atomic publication.
- Fenced publication tied to the active job lease.
- Persistent artifact repository and rebuild manifests.
- End-to-end worker handler wiring and extraction job scheduling.

Do not treat this adapter as permission to read arbitrary paths. Do not publish extracted payloads until the artifact store and fenced publication contract are implemented.
