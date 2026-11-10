# Persisted Lexical Search

**Status:** Initial local CLI search is implemented over persisted extracted-text artifacts.

## Usage

After a worker has completed one or more text extraction jobs:

```bash
pab search "project release owner" --limit 10
pab search "project release owner" --root-id <storage-root-uuid>
pab search "project release owner" --document-type md
pab search "project release owner" --modified-after 2025-01-01T00:00:00Z
```

The CLI returns a BM25 score and an evidence reference containing asset ID, immutable asset-version ID, storage-root ID, relative path, source SHA-256, and a short text snippet.

## Current implementation

- Reads only `ready` `extracted_text` artifacts whose asset version is still present at an available current location.
- Selects the latest artifact for each asset-version/root/path tuple.
- Applies root, extension/type, and source-modified-time filters in PostgreSQL before indexing.
- Uses the dependency-free BM25 implementation (k1=1.5, b=0.75) with deterministic tie-breaking.
- Builds an in-memory index for each search request; default safety bounds are 5,000 documents and 64 MiB of extracted text.
- Refuses to silently truncate a corpus that exceeds either bound.

## Limits and security boundary

- This is a local developer-preview search path, not a persistent inverted index or production-scale search service.
- Results identify an exact source version and path but do not yet provide token/character evidence spans.
- Search currently reads inline JSONB payloads. External artifact-blob retrieval is not implemented.
- The CLI is local-only; this repository adapter does not yet apply the future principal/scope policy engine or external-model egress rules. Do not expose it through an unauthenticated API/MCP endpoint.
- Semantic/vector retrieval and ranking fusion remain deferred until the labelled corpus is expanded and the lexical baseline is measured on representative data.
