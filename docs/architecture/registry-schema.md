# PostgreSQL Asset Registry Schema

**Status:** implementation proposal in PR review. The migration is the executable contract; this document records its semantics and limitations.

## Identity and duplicate policy

- A path is a location, never an asset identity.
- Asset IDs are random UUIDs assigned by the registry.
- An asset may have immutable content versions. A version is unique within its asset by SHA-256 plus byte size.
- Identical content across different assets is indexed as a duplicate candidate, not automatically merged. This avoids merging files across trust boundaries or unrelated user intent.
- A future explicit deduplication workflow may link assets, but must preserve original IDs and locations.

## Tables

| Table | Role |
|---|---|
| storage_roots | Configured local, network, and removable sources |
| assets | Logical file identities |
| asset_versions | Immutable content fingerprints and file metadata |
| asset_locations | Current and historical root-relative paths |
| scan_runs | Scan lifecycle and completeness |
| scan_observations | Immutable per-scan discovery evidence |
| asset_location_events | Availability and version transition history |
| processing_artifacts | Rebuildable derived outputs with processor/model provenance |
| audit_events | Access and policy decisions without document bodies |

## Reconciliation contract

The migration exposes `reconcile_missing_asset_locations(scan_run_id)`. It refuses every scan state except `complete`, requires a finish timestamp, and locks the scan row. It updates availability only for active locations under that scan's root and writes an event for each state transition.

Observations become immutable once the scan enters a terminal state. The caller must:
1. create a scan run in `pending` or `running`;
2. persist all observations;
3. set its terminal status and finish timestamp in the same transaction;
4. invoke reconciliation only when the terminal status is `complete`;
5. commit the transaction.

A `partial`, `failed`, or `cancelled` scan cannot invoke the reconciliation function and therefore cannot mark locations missing. An empty but genuinely completed scan can mark all previously present/excluded locations missing.

## Path semantics

Both the original observed path and the root-specific normalized comparison key are stored. The application must supply a versioned normalizer and must not assume case folding or Unicode normalization unless the root's filesystem policy is known. The unique active-path index prevents two current records from claiming the same normalized key under one root; a path reassignment must close the previous location interval before inserting the new occupant.

## Operational notes

- PostgreSQL 13+ is required for built-in `gen_random_uuid()`; PostgreSQL 15+ is recommended.
- The migration does not store source file bodies and does not issue filesystem operations.
- Foreign keys use RESTRICT to preserve provenance and history.
- The schema does not yet implement a full repository/service layer, connection pooling, retry policy, or cross-process reconciliation lease.
- The SQL integration tests are opt-in via `PERSONAL_AI_BRAIN_TEST_DATABASE_URL`; CI without a disposable PostgreSQL instance must report them as skipped, not passed.
