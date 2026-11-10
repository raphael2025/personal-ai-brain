# Durable Jobs and Worker Lease Foundation

**Status:** PostgreSQL schema and state-transition functions are under review in PR #38. This is not yet a complete worker runtime or production queue.

## Apply

Apply the Asset Registry migration first, then:

    psql "$PAB_DATABASE_URL" -v ON_ERROR_STOP=1 -f infrastructure/postgres/migrations/0002_durable_jobs.sql

The migration creates workers, processing jobs, job attempts, and database functions for enqueue, claim, heartbeat, complete, fail/retry, cancellation, and cancellation acknowledgement.

## Job identity

A caller supplies an idempotency key derived from the source version, task type, semantic processor version, and configuration digest. Repeating the same key with the same specification returns the existing job ID. Reusing the key for a different specification is rejected.

The source is an immutable `asset_version_id`, never a mutable path. The job payload is metadata for the worker; it must not contain credentials or unrestricted filesystem paths.

## Worker lifecycle

1. Register a worker with a stable UUID, display name, and capability list.
2. Call `claim_processing_job(worker_id, lease_seconds)`.
3. The claim is atomic and uses `FOR UPDATE SKIP LOCKED`; required capabilities must be a subset of worker capabilities.
4. Heartbeat using job ID, worker ID, and lease generation.
5. Complete, fail, or acknowledge cancellation using the same fencing tuple.

Lease duration is bounded to 5–86,400 seconds. A lease generation increases on every claim. Expired attempts are marked abandoned before a replacement claim. A stale worker cannot heartbeat, complete, fail, or acknowledge cancellation after a newer generation takes ownership.

## Retry and cancellation

- Retryable failures move to `retry_wait` only while attempts remain.
- Retry delay is deterministic exponential backoff, capped at five minutes.
- Non-retryable failures and exhausted attempts become terminal `failed`.
- Queued/retry-wait jobs cancel immediately.
- Active jobs enter `cancel_requested`; the lease holder must acknowledge cancellation. If its lease expires, the next claim operation finalizes cancellation.

## Current limitations

- No Python JobRepository adapter or worker process/CLI is included yet.
- Artifact staging, checksum validation, and atomic publication are not implemented.
- Worker registration currently uses direct database operations; authenticated worker enrollment is not implemented.
- Database functions are the current fencing boundary; database roles and network access still require deployment hardening.
- Backups, metrics, operational dashboards, and multi-node transport remain later work.

Do not expose PostgreSQL credentials to untrusted workers. Workers must not modify source files. Do not treat a claimed job as permission to access arbitrary roots; root-scoped authorization and isolated artifact sinks are still required.
