# ADR-0001: Local-first processing and source-of-truth boundaries

- **Status:** Accepted as a project principle
- **Date:** 2026-11-09

## Context

The system may index highly sensitive personal files spread across multiple devices and storage systems. Derived summaries, embeddings, and extracted entities can become stale or incorrect and must not replace original evidence.

## Decision

1. Original files remain in place and are read-only by default.
2. The registry records asset identity, locations, versions, and metadata; it does not become the canonical content store.
3. Derived artifacts must record provenance and processing versions.
4. Derived indexes must be rebuildable.
5. External model egress is disabled by default and requires explicit policy authorization.

## Consequences

- The system must handle unavailable and removable storage.
- File identity cannot depend solely on a path.
- Index refresh and deletion semantics require explicit design.
- Backups must cover registry metadata and derived state while preserving source ownership.
- Convenience must not override privacy or provenance.
