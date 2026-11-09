# Worker Contract

**Status:** proposed contract.

## Job lifecycle
QUEUED -> LEASED -> RUNNING -> SUCCEEDED

Alternative states: RETRYABLE_FAILED, FAILED, CANCELLED, EXPIRED.

## Required job fields
- Stable job ID
- Job type and schema version
- Input asset/version IDs
- Idempotency key
- Attempt count and maximum attempts
- Lease owner, lease expiry, and heartbeat timestamp
- Checkpoint payload (versioned and bounded)
- Created, started, and completed timestamps
- Structured error code and redacted diagnostic message

## Worker requirements
- Acknowledge a job only after a valid lease is acquired.
- Renew leases while processing.
- Use bounded CPU, memory, disk, and wall-clock budgets.
- Persist checkpoints at safe boundaries.
- Make retries idempotent.
- Do not silently convert parser errors into empty successful output.
- Record processor name/version and model identifier for every derived artifact.
- Treat all file contents and extracted text as untrusted input.
- Never write to original source files.

## Failure behavior
- Transient network or storage failures may be retried with bounded backoff.
- Unsupported formats should produce an explicit UNSUPPORTED outcome, not an infinite retry.
- Corrupt or malicious inputs should be quarantined from repeated processing and surfaced for review.
- Expired leases may be reclaimed; duplicate execution must remain safe.
- Worker shutdown must release or allow expiry of leases without losing checkpoints.
