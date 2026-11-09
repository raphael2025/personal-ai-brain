# Asset Registry — Domain Design

**Status:** initial domain primitives implemented; persistence and reconciliation remain planned.

## Core concepts
- **StorageRoot:** configured source such as a local directory, NAS share, or removable volume.
- **Asset:** logical file identity independent of one path or storage location.
- **AssetVersion:** immutable observation of file content, identified by cryptographic digest and size.
- **AssetLocation:** one observed path for an asset on a storage root.
- **ScanRun:** one discovery pass over a root, including start/end time and outcome.
- **ScanObservation:** file or directory observed during a scan.
- **ProcessingArtifact:** derived output tied to an asset version and processor/model version.

## Implemented domain primitives

- `StorageRoot`: logical source URI, kind, enabled flag, and explicit no-symlink policy.
- `AssetLocation`: normalized root-relative path and explicit availability state.
- `scan_directory`: read-only filesystem discovery with COMPLETE, PARTIAL, and FAILED outcomes.
- `identify_file`: bounded-memory SHA-256 identity for a regular file.

These are in-memory primitives only. There is not yet a persistent registry, database schema, or reconciliation engine.

## Identity rules
- A path is a location, not an identity.
- Content digest plus byte size identifies an exact observed content version.
- Two paths with identical content may be linked as duplicate locations, but do not automatically merge user-level semantic records.
- A changed digest creates a new AssetVersion.
- Rename/move detection is a reconciliation hypothesis based on content identity and root scope, not a destructive filesystem operation.
- Hashing must use bounded memory and detect files modified during reads.

## Scan semantics
A scan has explicit states: PENDING, RUNNING, COMPLETED, PARTIAL, FAILED, CANCELLED.

The initial scanner records relative paths and basic metadata, does not intentionally follow symlinks, and returns COMPLETE, PARTIAL, or FAILED. Only COMPLETE scans may be considered for absence reconciliation. PARTIAL and FAILED scans must never mark previously registered locations missing.

The scanner is not a hardened sandbox against an adversary concurrently replacing directory entries during traversal. Do not treat it as a security boundary for hostile, attacker-writable filesystems.

## Initial metadata
- Asset ID
- Version ID / SHA-256 / size
- MIME type and extension (both treated as hints)
- Created/modified timestamps where available, with source semantics recorded
- Storage root ID and relative path
- First seen / last seen timestamps
- Availability and scan provenance
- Exclusion and access classification

## Invariants
1. Never write to the source path.
2. Never treat an inaccessible root as an empty root.
3. Never delete registry history as a side effect of scanning.
4. Persist scan state and checkpoints.
5. Make repeated scans idempotent.
6. Preserve provenance for every extracted artifact.

## Open questions
- Which fingerprint tiers should be used for very large files (metadata fast path, partial hash, full hash)?
- How should case sensitivity and Unicode normalization be represented across filesystems?
- What policy should govern encrypted archives and symlinks?
- When should duplicate content be represented as one asset with multiple locations versus separate logical assets?
