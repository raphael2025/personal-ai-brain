-- Extend derived artifacts with immutable provenance and job-lease fencing.
-- Existing pre-v1 artifacts remain readable; new worker publications populate all fields.

ALTER TABLE processing_artifacts
    ADD COLUMN source_sha256 char(64),
    ADD COLUMN output_schema_version text,
    ADD COLUMN config_digest char(64),
    ADD COLUMN job_id uuid REFERENCES processing_jobs(id) ON DELETE RESTRICT,
    ADD COLUMN lease_generation bigint,
    ADD COLUMN published_by_worker_id uuid REFERENCES workers(id) ON DELETE RESTRICT,
    ADD COLUMN size_bytes bigint;

ALTER TABLE processing_artifacts
    ADD CONSTRAINT processing_artifacts_source_sha256_check
        CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT processing_artifacts_config_digest_check
        CHECK (config_digest IS NULL OR config_digest ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT processing_artifacts_size_bytes_check
        CHECK (size_bytes IS NULL OR size_bytes >= 0),
    ADD CONSTRAINT processing_artifacts_lease_provenance_check
        CHECK (
            (job_id IS NULL AND lease_generation IS NULL AND published_by_worker_id IS NULL)
            OR
            (job_id IS NOT NULL AND lease_generation > 0 AND published_by_worker_id IS NOT NULL)
        ),
    ADD CONSTRAINT processing_artifacts_schema_version_check
        CHECK (output_schema_version IS NULL OR length(btrim(output_schema_version)) > 0);

-- One deterministic artifact identity per source version + processor/configuration.
-- This makes retries and duplicate delivery idempotent across distinct jobs.
CREATE UNIQUE INDEX processing_artifacts_identity_idx
    ON processing_artifacts (
        asset_version_id,
        artifact_type,
        processor_name,
        processor_version,
        output_schema_version,
        config_digest
    )
    WHERE config_digest IS NOT NULL;

CREATE INDEX processing_artifacts_job_idx
    ON processing_artifacts (job_id, lease_generation)
    WHERE job_id IS NOT NULL;
