# ADR-0003: PAB owns asset identity and evidence provenance

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Personal AI Brain may integrate context databases, memory engines, graph extractors, vector stores, and external AI clients. These systems have different schemas, storage semantics, deletion behavior, and release cycles. If any integration becomes authoritative for asset identity or provenance, replacing it later could break source references, permissions, and audit history.

The original file remains the source of truth. PAB must preserve a stable identity across path changes, storage disconnections, and changes in retrieval providers.

## Decision

1. PAB Asset Registry owns the canonical asset_id, asset_version_id, storage-root identity, location history, scan history, and source-version provenance.
2. A path is a location observation, never an asset identity.
3. A content fingerprint is a matching signal, not permission to merge two logical assets.
4. Extractors and external knowledge/memory engines produce derived artifacts keyed by PAB asset/version IDs and processor manifests.
5. External engines are optional adapters/projections. They may not mint canonical asset IDs, rewrite source files, or silently mutate PAB provenance.
6. Deleting or replacing an external engine must not destroy PAB's source registry or make original evidence unresolvable.
7. Every result returned through an adapter must map back to a PAB source version and evidence reference, or be explicitly labelled as ungrounded.

## Consequences

- Adapter contracts must include export, deletion, re-indexing, and provenance mapping tests.
- PAB can experiment with OpenViking, MemOS, Cognee, and other engines without making them mandatory runtime dependencies.
- Duplicate-content detection and rename suggestions remain reviewable workflows; no automatic logical-asset merge is permitted.
- Retrieval caches and graph/vector indexes are disposable projections and must be rebuildable.
- Integrations that cannot preserve stable source references are unsuitable for factual retrieval in PAB.
