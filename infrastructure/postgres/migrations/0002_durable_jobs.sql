-- Personal AI Brain: durable jobs, worker leases, and fencing.
-- This migration adds only derived-work orchestration; it never writes source files.

CREATE TABLE workers (
    id uuid PRIMARY KEY,
    display_name text NOT NULL CHECK (length(btrim(display_name)) > 0),
    capabilities text[] NOT NULL DEFAULT '{}',
    enabled boolean NOT NULL DEFAULT true,
    last_heartbeat_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (array_position(capabilities, NULL) IS NULL)
);

CREATE TABLE processing_jobs (
    id uuid PRIMARY KEY,
    asset_version_id uuid NOT NULL REFERENCES asset_versions(id) ON DELETE RESTRICT,
    task_type text NOT NULL CHECK (length(btrim(task_type)) > 0),
    semantic_version text NOT NULL CHECK (length(btrim(semantic_version)) > 0),
    config_digest char(64) NOT NULL CHECK (config_digest ~ '^[0-9a-f]{64}$'),
    idempotency_key text NOT NULL UNIQUE CHECK (length(btrim(idempotency_key)) > 0),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    required_capabilities text[] NOT NULL DEFAULT '{}',
    priority integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN (
            'queued', 'leased', 'running', 'retry_wait',
            'succeeded', 'failed', 'cancel_requested', 'cancelled'
        )
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_generation bigint NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_owner_worker_id uuid REFERENCES workers(id) ON DELETE RESTRICT,
    lease_expires_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (array_position(required_capabilities, NULL) IS NULL),
    CHECK (attempt_count <= max_attempts),
    CHECK (
        (status IN ('leased', 'running', 'cancel_requested')
            AND lease_owner_worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR
        (status NOT IN ('leased', 'running', 'cancel_requested')
            AND lease_owner_worker_id IS NULL AND lease_expires_at IS NULL)
    ),
    CHECK (
        (status IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL)
        OR
        (status NOT IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NULL)
    )
);

CREATE INDEX processing_jobs_claim_idx
    ON processing_jobs (priority DESC, available_at, created_at, id)
    WHERE status IN ('queued', 'retry_wait', 'leased', 'running');

CREATE INDEX processing_jobs_asset_version_idx
    ON processing_jobs (asset_version_id, task_type, created_at DESC);

CREATE TABLE job_attempts (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES processing_jobs(id) ON DELETE RESTRICT,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    lease_generation bigint NOT NULL CHECK (lease_generation > 0),
    worker_id uuid NOT NULL REFERENCES workers(id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (
        status IN ('running', 'succeeded', 'retry_wait', 'failed', 'abandoned', 'cancelled')
    ),
    started_at timestamptz NOT NULL DEFAULT now(),
    heartbeat_at timestamptz NOT NULL DEFAULT now(),
    lease_expires_at timestamptz NOT NULL,
    finished_at timestamptz,
    error_summary text,
    UNIQUE (job_id, attempt_no),
    UNIQUE (job_id, lease_generation),
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status <> 'running' AND finished_at IS NOT NULL)
    )
);

CREATE INDEX job_attempts_worker_status_idx
    ON job_attempts (worker_id, status, lease_expires_at);

CREATE INDEX job_attempts_job_started_idx
    ON job_attempts (job_id, started_at DESC);

-- Enqueue is idempotent. Reusing a key for a different specification is rejected.
CREATE FUNCTION enqueue_processing_job(
    p_id uuid,
    p_asset_version_id uuid,
    p_task_type text,
    p_semantic_version text,
    p_config_digest text,
    p_idempotency_key text,
    p_payload jsonb DEFAULT '{}'::jsonb,
    p_required_capabilities text[] DEFAULT '{}',
    p_priority integer DEFAULT 0,
    p_max_attempts integer DEFAULT 3
)
RETURNS uuid
LANGUAGE plpgsql
AS $function$
DECLARE
    v_existing processing_jobs%ROWTYPE;
BEGIN
    IF p_idempotency_key IS NULL OR length(btrim(p_idempotency_key)) = 0 THEN
        RAISE EXCEPTION 'idempotency key must not be empty';
    END IF;
    IF p_max_attempts NOT BETWEEN 1 AND 20 THEN
        RAISE EXCEPTION 'max_attempts must be between 1 and 20';
    END IF;

    INSERT INTO processing_jobs (
        id, asset_version_id, task_type, semantic_version, config_digest,
        idempotency_key, payload, required_capabilities, priority, max_attempts
    )
    VALUES (
        p_id, p_asset_version_id, p_task_type, p_semantic_version, p_config_digest,
        p_idempotency_key, COALESCE(p_payload, '{}'::jsonb),
        COALESCE(p_required_capabilities, '{}'), p_priority, p_max_attempts
    )
    ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO v_existing
      FROM processing_jobs
     WHERE idempotency_key = p_idempotency_key
     FOR SHARE;

    IF v_existing.asset_version_id <> p_asset_version_id
       OR v_existing.task_type <> p_task_type
       OR v_existing.semantic_version <> p_semantic_version
       OR v_existing.config_digest <> p_config_digest
       OR v_existing.payload <> COALESCE(p_payload, '{}'::jsonb)
       OR v_existing.required_capabilities <> COALESCE(p_required_capabilities, '{}')
       OR v_existing.priority <> p_priority
       OR v_existing.max_attempts <> p_max_attempts THEN
        RAISE EXCEPTION 'idempotency key reused with a different job specification';
    END IF;

    RETURN v_existing.id;
END;
$function$;

-- Claim one compatible job atomically. Expired leases are abandoned and fenced.
CREATE FUNCTION claim_processing_job(p_worker_id uuid, p_lease_seconds integer)
RETURNS TABLE (
    job_id uuid,
    asset_version_id uuid,
    task_type text,
    semantic_version text,
    config_digest text,
    payload jsonb,
    attempt_no integer,
    lease_generation bigint,
    lease_expires_at timestamptz
)
LANGUAGE plpgsql
AS $function$
DECLARE
    v_worker workers%ROWTYPE;
    v_job processing_jobs%ROWTYPE;
    v_expiry timestamptz;
    v_attempt integer;
    v_generation bigint;
BEGIN
    IF p_lease_seconds NOT BETWEEN 5 AND 86400 THEN
        RAISE EXCEPTION 'lease duration must be between 5 and 86400 seconds';
    END IF;

    SELECT * INTO v_worker FROM workers
     WHERE id = p_worker_id AND enabled = true
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'worker is unknown or disabled';
    END IF;

    -- Expired cancellation requests become terminal instead of remaining stuck.
    UPDATE job_attempts AS a
       SET status = 'cancelled', finished_at = now(),
           error_summary = 'cancellation acknowledged by lease expiry'
      FROM processing_jobs AS j
     WHERE a.job_id = j.id
       AND a.lease_generation = j.lease_generation
       AND a.status = 'running'
       AND j.status = 'cancel_requested'
       AND j.lease_expires_at <= now();

    UPDATE processing_jobs
       SET status = 'cancelled', finished_at = now(), updated_at = now(),
           lease_owner_worker_id = NULL, lease_expires_at = NULL
     WHERE status = 'cancel_requested' AND lease_expires_at <= now();

    -- A final attempt whose lease expired cannot be claimed again.
    UPDATE job_attempts AS a
       SET status = 'failed', finished_at = now(),
           error_summary = 'final lease expired before completion'
      FROM processing_jobs AS j
     WHERE a.job_id = j.id
       AND a.lease_generation = j.lease_generation
       AND a.status = 'running'
       AND j.status IN ('leased', 'running')
       AND j.lease_expires_at <= now()
       AND j.attempt_count >= j.max_attempts;

    UPDATE processing_jobs
       SET status = 'failed', finished_at = now(), updated_at = now(),
           last_error = 'final lease expired before completion',
           lease_owner_worker_id = NULL, lease_expires_at = NULL
     WHERE status IN ('leased', 'running')
       AND lease_expires_at <= now()
       AND attempt_count >= max_attempts;

    SELECT j.* INTO v_job
      FROM processing_jobs AS j
     WHERE j.available_at <= now()
       AND j.attempt_count < j.max_attempts
       AND (
           j.status IN ('queued', 'retry_wait')
           OR (j.status IN ('leased', 'running') AND j.lease_expires_at <= now())
       )
       AND j.required_capabilities <@ v_worker.capabilities
     ORDER BY j.priority DESC, j.available_at, j.created_at, j.id
     LIMIT 1
     FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF v_job.lease_owner_worker_id IS NOT NULL THEN
        UPDATE job_attempts
           SET status = 'abandoned',
               finished_at = now(),
               error_summary = 'lease expired before completion'
         WHERE job_id = v_job.id
           AND lease_generation = v_job.lease_generation
           AND status = 'running';
    END IF;

    v_attempt := v_job.attempt_count + 1;
    v_generation := v_job.lease_generation + 1;
    v_expiry := now() + make_interval(secs => p_lease_seconds);

    UPDATE processing_jobs
       SET status = 'leased',
           attempt_count = v_attempt,
           lease_generation = v_generation,
           lease_owner_worker_id = p_worker_id,
           lease_expires_at = v_expiry,
           started_at = COALESCE(started_at, now()),
           updated_at = now()
     WHERE id = v_job.id;

    INSERT INTO job_attempts (
        id, job_id, attempt_no, lease_generation, worker_id,
        status, started_at, heartbeat_at, lease_expires_at
    )
    VALUES (
        gen_random_uuid(), v_job.id, v_attempt, v_generation, p_worker_id,
        'running', now(), now(), v_expiry
    );

    UPDATE workers SET last_heartbeat_at = now(), updated_at = now()
     WHERE id = p_worker_id;

    RETURN QUERY SELECT
        v_job.id, v_job.asset_version_id, v_job.task_type,
        v_job.semantic_version, v_job.config_digest, v_job.payload,
        v_attempt, v_generation, v_expiry;
END;
$function$;

-- Only the current, unexpired lease holder can extend the lease.
CREATE FUNCTION heartbeat_processing_job(
    p_job_id uuid, p_worker_id uuid, p_generation bigint, p_lease_seconds integer
)
RETURNS timestamptz
LANGUAGE plpgsql
AS $function$
DECLARE
    v_expiry timestamptz;
BEGIN
    IF p_lease_seconds NOT BETWEEN 5 AND 86400 THEN
        RAISE EXCEPTION 'lease duration must be between 5 and 86400 seconds';
    END IF;

    UPDATE processing_jobs
       SET status = 'running',
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     WHERE id = p_job_id
       AND lease_owner_worker_id = p_worker_id
       AND lease_generation = p_generation
       AND status IN ('leased', 'running')
       AND lease_expires_at > now()
       AND EXISTS (SELECT 1 FROM workers WHERE id = p_worker_id AND enabled)
    RETURNING lease_expires_at INTO v_expiry;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'LEASE_LOST: worker no longer owns an active lease';
    END IF;

    UPDATE job_attempts
       SET heartbeat_at = now(), lease_expires_at = v_expiry
     WHERE job_id = p_job_id AND lease_generation = p_generation
       AND worker_id = p_worker_id AND status = 'running';

    UPDATE workers SET last_heartbeat_at = now(), updated_at = now()
     WHERE id = p_worker_id;
    RETURN v_expiry;
END;
$function$;

-- Completion is fenced. A stale worker cannot publish a successful result.
CREATE FUNCTION complete_processing_job(
    p_job_id uuid, p_worker_id uuid, p_generation bigint
)
RETURNS void
LANGUAGE plpgsql
AS $function$
BEGIN
    UPDATE processing_jobs
       SET status = 'succeeded', finished_at = now(), updated_at = now(),
           lease_owner_worker_id = NULL, lease_expires_at = NULL
     WHERE id = p_job_id
       AND lease_owner_worker_id = p_worker_id
       AND lease_generation = p_generation
       AND status IN ('leased', 'running')
       AND lease_expires_at > now();

    IF NOT FOUND THEN
        RAISE EXCEPTION 'LEASE_LOST: stale worker cannot complete this job';
    END IF;

    UPDATE job_attempts
       SET status = 'succeeded', finished_at = now(), heartbeat_at = now()
     WHERE job_id = p_job_id AND lease_generation = p_generation
       AND worker_id = p_worker_id AND status = 'running';
END;
$function$;

-- Failures are bounded; retry delay is deterministic and capped at five minutes.
CREATE FUNCTION fail_processing_job(
    p_job_id uuid, p_worker_id uuid, p_generation bigint,
    p_error text, p_retryable boolean DEFAULT true
)
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_job processing_jobs%ROWTYPE;
    v_next_status text;
    v_delay integer;
BEGIN
    SELECT * INTO v_job FROM processing_jobs
     WHERE id = p_job_id FOR UPDATE;
    IF NOT FOUND
       OR v_job.lease_owner_worker_id IS DISTINCT FROM p_worker_id
       OR v_job.lease_generation <> p_generation
       OR v_job.status NOT IN ('leased', 'running')
       OR v_job.lease_expires_at <= now() THEN
        RAISE EXCEPTION 'LEASE_LOST: stale worker cannot fail this job';
    END IF;

    IF p_retryable AND v_job.attempt_count < v_job.max_attempts THEN
        v_next_status := 'retry_wait';
        v_delay := LEAST(300, power(2, LEAST(v_job.attempt_count, 8))::integer);
    ELSE
        v_next_status := 'failed';
        v_delay := 0;
    END IF;

    UPDATE processing_jobs
       SET status = v_next_status,
           available_at = CASE WHEN v_next_status = 'retry_wait'
                               THEN now() + make_interval(secs => v_delay)
                               ELSE available_at END,
           finished_at = CASE WHEN v_next_status = 'failed' THEN now() ELSE NULL END,
           last_error = left(COALESCE(p_error, 'unspecified worker failure'), 1000),
           lease_owner_worker_id = NULL,
           lease_expires_at = NULL,
           updated_at = now()
     WHERE id = p_job_id;

    UPDATE job_attempts
       SET status = v_next_status,
           finished_at = now(),
           error_summary = left(COALESCE(p_error, 'unspecified worker failure'), 1000)
     WHERE job_id = p_job_id AND lease_generation = p_generation
       AND worker_id = p_worker_id AND status = 'running';

    RETURN v_next_status;
END;
$function$;

-- Queued jobs cancel immediately; active jobs receive a cancellation request.
CREATE FUNCTION request_processing_job_cancel(p_job_id uuid)
RETURNS text
LANGUAGE plpgsql
AS $function$
DECLARE
    v_status text;
BEGIN
    UPDATE processing_jobs
       SET status = CASE
               WHEN status IN ('queued', 'retry_wait') THEN 'cancelled'
               WHEN status IN ('leased', 'running') THEN 'cancel_requested'
               ELSE status
           END,
           finished_at = CASE
               WHEN status IN ('queued', 'retry_wait') THEN now()
               ELSE finished_at
           END,
           updated_at = now()
     WHERE id = p_job_id
       AND status IN ('queued', 'retry_wait', 'leased', 'running')
    RETURNING status INTO v_status;

    IF NOT FOUND THEN
        SELECT status INTO v_status FROM processing_jobs WHERE id = p_job_id;
        IF v_status IS NULL THEN
            RAISE EXCEPTION 'job not found: %', p_job_id;
        END IF;
    END IF;
    RETURN v_status;
END;
$function$;

CREATE FUNCTION acknowledge_processing_job_cancel(
    p_job_id uuid, p_worker_id uuid, p_generation bigint
)
RETURNS void
LANGUAGE plpgsql
AS $function$
BEGIN
    UPDATE processing_jobs
       SET status = 'cancelled', finished_at = now(), updated_at = now(),
           lease_owner_worker_id = NULL, lease_expires_at = NULL
     WHERE id = p_job_id
       AND status = 'cancel_requested'
       AND lease_owner_worker_id = p_worker_id
       AND lease_generation = p_generation
       AND lease_expires_at > now();

    IF NOT FOUND THEN
        RAISE EXCEPTION 'LEASE_LOST: worker cannot acknowledge this cancellation';
    END IF;

    UPDATE job_attempts
       SET status = 'cancelled', finished_at = now()
     WHERE job_id = p_job_id AND lease_generation = p_generation
       AND worker_id = p_worker_id AND status = 'running';
END;
$function$;
