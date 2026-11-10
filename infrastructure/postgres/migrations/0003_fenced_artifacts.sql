-- Fenced artifact staging: only the current active job lease may stage metadata.
-- Artifacts become visible (ready) only when the job completes successfully.

ALTER TABLE processing_artifacts
    ADD COLUMN job_id uuid REFERENCES processing_jobs(id) ON DELETE RESTRICT,
    ADD COLUMN worker_id uuid REFERENCES workers(id) ON DELETE RESTRICT,
    ADD COLUMN lease_generation bigint,
    ADD COLUMN config_digest char(64),
    ADD COLUMN output_schema_version text,
    ADD COLUMN size_bytes bigint;

ALTER TABLE processing_artifacts
    ADD CONSTRAINT processing_artifacts_lease_metadata_ck CHECK (
        (job_id IS NULL AND worker_id IS NULL AND lease_generation IS NULL)
        OR
        (job_id IS NOT NULL AND worker_id IS NOT NULL AND lease_generation > 0)
    ),
    ADD CONSTRAINT processing_artifacts_config_digest_ck CHECK (
        config_digest IS NULL OR config_digest ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT processing_artifacts_size_ck CHECK (
        size_bytes IS NULL OR size_bytes >= 0
    );

CREATE UNIQUE INDEX processing_artifacts_job_output_uq
    ON processing_artifacts (
        job_id, lease_generation, artifact_type, processor_name, processor_version
    )
    WHERE job_id IS NOT NULL;

CREATE INDEX processing_artifacts_job_state_idx
    ON processing_artifacts (job_id, lease_generation, status)
    WHERE job_id IS NOT NULL;

CREATE FUNCTION stage_processing_artifact(
    p_artifact_id uuid,
    p_job_id uuid,
    p_worker_id uuid,
    p_lease_generation bigint,
    p_asset_version_id uuid,
    p_artifact_type text,
    p_processor_name text,
    p_processor_version text,
    p_output_schema_version text,
    p_config_digest text,
    p_artifact_uri text,
    p_content_sha256 text,
    p_size_bytes bigint
)
RETURNS uuid
LANGUAGE plpgsql
AS $function$
DECLARE
    v_asset_version_id uuid;
    v_existing processing_artifacts%ROWTYPE;
    v_inserted_id uuid;
BEGIN
    IF p_content_sha256 IS NULL OR p_content_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'content_sha256 must be a lowercase SHA-256 digest';
    END IF;
    IF p_config_digest IS NULL OR p_config_digest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'config_digest must be a lowercase SHA-256 digest';
    END IF;
    IF p_size_bytes IS NULL OR p_size_bytes < 0 THEN
        RAISE EXCEPTION 'artifact size must be non-negative';
    END IF;
    IF p_artifact_uri IS DISTINCT FROM
       ('artifact://sha256/' || substr(p_content_sha256, 1, 2) || '/' || p_content_sha256) THEN
        RAISE EXCEPTION 'artifact URI must be the canonical content-addressed URI';
    END IF;

    SELECT j.asset_version_id INTO v_asset_version_id
      FROM processing_jobs AS j
     WHERE j.id = p_job_id
       AND j.asset_version_id = p_asset_version_id
       AND j.lease_owner_worker_id = p_worker_id
       AND j.lease_generation = p_lease_generation
       AND j.status IN ('leased', 'running')
       AND j.lease_expires_at > clock_timestamp()
       AND EXISTS (SELECT 1 FROM workers AS w WHERE w.id = p_worker_id AND w.enabled)
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'LEASE_LOST: artifact staging requires the current active lease';
    END IF;

    INSERT INTO processing_artifacts (
        id, asset_version_id, artifact_type, processor_name, processor_version,
        artifact_uri, content_sha256, status, job_id, worker_id, lease_generation,
        config_digest, output_schema_version, size_bytes
    )
    VALUES (
        p_artifact_id, p_asset_version_id, p_artifact_type, p_processor_name,
        p_processor_version, p_artifact_uri, p_content_sha256, 'pending',
        p_job_id, p_worker_id, p_lease_generation, p_config_digest,
        p_output_schema_version, p_size_bytes
    )
    ON CONFLICT (
        job_id, lease_generation, artifact_type, processor_name, processor_version
    ) WHERE job_id IS NOT NULL DO NOTHING
    RETURNING id INTO v_inserted_id;

    IF v_inserted_id IS NOT NULL THEN
        RETURN v_inserted_id;
    END IF;

    SELECT * INTO v_existing
      FROM processing_artifacts
     WHERE job_id = p_job_id
       AND lease_generation = p_lease_generation
       AND artifact_type = p_artifact_type
       AND processor_name = p_processor_name
       AND processor_version = p_processor_version
     FOR UPDATE;

    IF v_existing.asset_version_id <> p_asset_version_id
       OR v_existing.worker_id <> p_worker_id
       OR v_existing.config_digest <> p_config_digest
       OR v_existing.artifact_uri <> p_artifact_uri
       OR v_existing.content_sha256 <> p_content_sha256
       OR v_existing.size_bytes <> p_size_bytes
       OR v_existing.output_schema_version <> p_output_schema_version THEN
        RAISE EXCEPTION 'artifact idempotency conflict for job lease';
    END IF;

    RETURN v_existing.id;
END;
$function$;

-- Pending artifacts are invisible until job success. Retry/failure/cancel or
-- a newer lease generation makes prior staged artifacts stale.
CREATE FUNCTION sync_processing_artifact_state_from_job()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.lease_generation > OLD.lease_generation THEN
        UPDATE processing_artifacts
           SET status = 'stale'
         WHERE job_id = NEW.id
           AND lease_generation = OLD.lease_generation
           AND status = 'pending';
    END IF;

    IF NEW.status = 'succeeded' AND OLD.status IS DISTINCT FROM NEW.status THEN
        UPDATE processing_artifacts
           SET status = 'ready'
         WHERE job_id = NEW.id
           AND lease_generation = NEW.lease_generation
           AND status = 'pending';
    ELSIF NEW.status IN ('retry_wait', 'failed', 'cancelled')
          AND OLD.status IS DISTINCT FROM NEW.status THEN
        UPDATE processing_artifacts
           SET status = 'stale'
         WHERE job_id = NEW.id
           AND lease_generation = OLD.lease_generation
           AND status = 'pending';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE TRIGGER processing_jobs_sync_artifacts
    AFTER UPDATE OF status, lease_generation ON processing_jobs
    FOR EACH ROW EXECUTE FUNCTION sync_processing_artifact_state_from_job();

COMMENT ON FUNCTION stage_processing_artifact(
    uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, text, text, bigint
) IS
    'Stages an artifact under a current job lease; it becomes ready only when that lease completes the job.';
