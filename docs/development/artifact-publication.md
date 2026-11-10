# Lease-Fenced Artifact Publication

**Status:** Initial PostgreSQL JSON-payload publication adapter implemented. This is not yet a full filesystem/blob artifact store or end-to-end extraction worker.

## Migration

Apply migrations in order:

1. `0001_asset_registry.sql`
2. `0002_durable_jobs.sql`
3. `0003_fenced_artifact_publication.sql`

The third migration adds source digest, output schema version, configuration digest, job/lease provenance, worker identity, and output size. A partial unique index enforces one deterministic artifact identity per source version, artifact type, processor/version, schema version, and configuration digest.

## Publication contract

`PostgresArtifactRepository.publish(lease, artifact, config_digest=...)`:

- Requires the artifact source version to match the job's immutable asset version.
- Locks the job row and checks worker identity, lease generation, active status, and expiry using the database clock.
- Requires the supplied config digest to match the durable job.
- Verifies the artifact source SHA-256 against `asset_versions`.
- Inserts the payload and provenance in one database transaction.
- Treats a repeated identical output as idempotent, including across duplicate jobs.
- Rejects a repeated identity with different output.
- Rejects stale, expired, cancelled, or superseded leases before publication.

The job row lock serializes publication against lease reclamation and completion transitions. Publication is valid only when the lease is current at the database check.

## Current limitations

- Payloads are stored in PostgreSQL JSONB for the initial bounded-text path.
- There is no content-addressed filesystem/object store, temporary staging directory, orphan garbage collector, or atomic blob/DB commit protocol yet.
- This adapter does not grant workers permission to read source paths.
- The worker runtime is not yet wired to this repository or to an extraction handler.
- Large binary and media artifacts are out of scope.
