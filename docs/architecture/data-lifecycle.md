# Data Lifecycle and Storage Contract

**Status:** proposed implementation contract.

## Data classes

| Class | Examples | Authority | Default handling |
|---|---|---|---|
| Source | PDF, code, photo, audio, archive | Original file | Read-only, remains in place |
| Registry | IDs, versions, locations, scans | Registry database | Durable and backed up |
| Extracted | text, OCR, transcript, metadata | Derived from source version | Rebuildable |
| Knowledge | chunks, entities, relations, claims | Evidence-linked derived data | Rebuildable where possible |
| Memory | user-authored facts and approved summaries | Depends on origin | Versioned, user-controlled |
| Index | BM25, embeddings, graph index | Derived | Disposable/rebuildable |
| Policy | principals, scopes, consent | Explicit user/admin decisions | Durable and protected |
| Audit | access, decisions, mutations | Append-only | Configurable retention |

## Root enrollment

Explicit enrollment records opaque root ID, normalized URI, user label, owner, include/exclude rules, scan policy, data classification, permitted processing locations, and last availability/complete scan. Incidental path discovery never silently enrolls a root.

## Asset lifecycle

1. Discovery emits path and metadata observations.
2. Identity resolution matches observations using root identity, path history, and fingerprints.
3. New content creates a new AssetVersion; unchanged content refreshes last-seen metadata.
4. Path changes create location events; they do not erase history.
5. Missing locations are inferred only after COMPLETE scans of the same root and scope.
6. Offline roots update availability, never asset existence.
7. Ambiguous matches enter review; no destructive auto-merge.

## Processing lifecycle

Artifact identity includes asset ID, immutable version ID, task/extractor name and semantic version, configuration digest, model identifier/version if relevant, and output schema version. Any relevant key change creates a new artifact generation. A worker cannot overwrite output for another source version.

## Memory origin and state

Origins:
- USER_AUTHORED
- USER_CONFIRMED
- SOURCE_DERIVED
- MODEL_INFERRED

Only user-authored or user-confirmed memories may be treated as user preferences/instructions. Source-derived and inferred items remain attributed claims.

States:
- CANDIDATE → ACTIVE → STALE → ARCHIVED
- CANDIDATE → REJECTED
- ACTIVE → CONFLICTED → ACTIVE after explicit resolution
- ACTIVE → ARCHIVED

Every transition records actor, reason, time, and evidence. Model inference cannot promote itself to user-confirmed.

## Retention and deletion

- PAB never deletes source files.
- Derived artifacts/indexes may be rebuilt; deletion requires retention policy and audit.
- Memory deletion invalidates derived copies, caches, and affected indexes.
- Audit avoids sensitive content; retention/export is configurable.
- Backups are encrypted and restore-tested.
- Registry deletion never implies source deletion.
- Source deletion observed by a complete scan creates a tombstone/history event; it does not cascade-delete provenance or audit history.

## Rebuildability

A rebuild manifest records source version IDs, extractor versions, config digests, schema versions, and index versions. Support rebuilding lexical indexes from extracted text, vector indexes from chunks and pinned embedding models, and summaries only with explicit model/version and provenance. Verify checksums after restore.

## Privacy defaults

Do not persist raw prompts unless query history is enabled. Do not log document bodies, OCR, transcripts, embeddings, or absolute paths by default. Scope content caches by principal and short TTL. Enforce per-root processing and provider-egress permissions. Provide export/deletion for registry metadata and derived artifacts.
