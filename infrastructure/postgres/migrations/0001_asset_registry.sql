-- Personal AI Brain: initial persistent Asset Registry.
-- Original source files remain outside PostgreSQL and are never modified here.

CREATE TABLE storage_roots (
    id uuid PRIMARY KEY,
    display_name text NOT NULL CHECK (length(btrim(display_name)) > 0),
    uri text NOT NULL CHECK (length(btrim(uri)) > 0),
    kind text NOT NULL CHECK (kind IN ('local', 'network', 'removable')),
    enabled boolean NOT NULL DEFAULT true,
    follow_symlinks boolean NOT NULL DEFAULT false CHECK (follow_symlinks = false),
    path_case_sensitive boolean,
    path_normalizer_version text NOT NULL DEFAULT 'v1',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assets (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE asset_versions (
    id uuid PRIMARY KEY,
    asset_id uuid NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    detected_mime_type text,
    observed_modified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (asset_id, sha256, size_bytes),
    UNIQUE (id, asset_id)
);

CREATE INDEX asset_versions_fingerprint_idx
    ON asset_versions (sha256, size_bytes);

CREATE TABLE scan_runs (
    id uuid PRIMARY KEY,
    storage_root_id uuid NOT NULL REFERENCES storage_roots(id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (
        status IN ('pending', 'running', 'complete', 'partial', 'failed', 'cancelled')
    ),
    scanner_version text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error_summary text,
    CHECK (
        (status IN ('pending', 'running') AND finished_at IS NULL)
        OR (status IN ('complete', 'partial', 'failed', 'cancelled') AND finished_at IS NOT NULL)
    )
);

CREATE INDEX scan_runs_root_started_idx
    ON scan_runs (storage_root_id, started_at DESC);

CREATE TABLE asset_locations (
    id uuid PRIMARY KEY,
    asset_id uuid NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
    storage_root_id uuid NOT NULL REFERENCES storage_roots(id) ON DELETE RESTRICT,
    current_version_id uuid,
    relative_path text NOT NULL CHECK (length(relative_path) > 0),
    normalized_path_key text NOT NULL CHECK (length(normalized_path_key) > 0),
    path_normalizer_version text NOT NULL,
    availability text NOT NULL DEFAULT 'present' CHECK (
        availability IN ('present', 'missing', 'unavailable', 'excluded')
    ),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    FOREIGN KEY (current_version_id, asset_id)
        REFERENCES asset_versions(id, asset_id) ON DELETE RESTRICT,
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

-- At most one current logical occupant for a normalized path under a root.
-- Historical rows remain queryable after valid_to is set.
CREATE UNIQUE INDEX asset_locations_current_path_uq
    ON asset_locations (storage_root_id, normalized_path_key)
    WHERE valid_to IS NULL;

CREATE INDEX asset_locations_asset_idx
    ON asset_locations (asset_id, valid_to);

CREATE INDEX asset_locations_availability_idx
    ON asset_locations (storage_root_id, availability)
    WHERE valid_to IS NULL;

CREATE TABLE scan_observations (
    id uuid PRIMARY KEY,
    scan_run_id uuid NOT NULL REFERENCES scan_runs(id) ON DELETE RESTRICT,
    relative_path text NOT NULL CHECK (length(relative_path) > 0),
    normalized_path_key text NOT NULL CHECK (length(normalized_path_key) > 0),
    path_normalizer_version text NOT NULL,
    entry_kind text NOT NULL CHECK (entry_kind IN ('file', 'directory', 'symlink', 'other')),
    size_bytes bigint NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    modified_time_ns bigint,
    asset_version_id uuid REFERENCES asset_versions(id) ON DELETE RESTRICT,
    is_excluded boolean NOT NULL DEFAULT false,
    observed_at timestamptz NOT NULL DEFAULT now(),
    CHECK (entry_kind = 'file' OR asset_version_id IS NULL),
    UNIQUE (scan_run_id, relative_path),
    UNIQUE (scan_run_id, normalized_path_key, path_normalizer_version)
);

CREATE INDEX scan_observations_path_idx
    ON scan_observations (scan_run_id, normalized_path_key, path_normalizer_version);

CREATE TABLE asset_location_events (
    id uuid PRIMARY KEY,
    asset_location_id uuid NOT NULL REFERENCES asset_locations(id) ON DELETE RESTRICT,
    scan_run_id uuid REFERENCES scan_runs(id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (
        event_type IN ('availability_changed', 'version_changed', 'path_reassigned')
    ),
    previous_availability text,
    new_availability text,
    previous_version_id uuid REFERENCES asset_versions(id) ON DELETE RESTRICT,
    new_version_id uuid REFERENCES asset_versions(id) ON DELETE RESTRICT,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX asset_location_events_location_idx
    ON asset_location_events (asset_location_id, occurred_at DESC);

CREATE TABLE processing_artifacts (
    id uuid PRIMARY KEY,
    asset_version_id uuid NOT NULL REFERENCES asset_versions(id) ON DELETE RESTRICT,
    artifact_type text NOT NULL,
    processor_name text NOT NULL,
    processor_version text NOT NULL,
    model_identifier text,
    artifact_uri text,
    payload jsonb,
    content_sha256 char(64),
    status text NOT NULL DEFAULT 'ready' CHECK (
        status IN ('pending', 'ready', 'failed', 'stale')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (artifact_uri IS NOT NULL OR payload IS NOT NULL),
    CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX processing_artifacts_version_idx
    ON processing_artifacts (asset_version_id, artifact_type, created_at DESC);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY,
    actor text NOT NULL,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id text,
    decision text NOT NULL CHECK (decision IN ('allowed', 'denied', 'recorded')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_events_occurred_idx ON audit_events (occurred_at DESC);

-- Observations are immutable once a scan reaches a terminal state.
CREATE FUNCTION prevent_closed_scan_observation_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_scan_id uuid;
    target_status text;
BEGIN
    target_scan_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.scan_run_id ELSE NEW.scan_run_id END;
    SELECT status INTO target_status FROM scan_runs WHERE id = target_scan_id FOR SHARE;
    IF target_status IS NULL THEN
        RAISE EXCEPTION 'scan run % does not exist', target_scan_id;
    END IF;
    IF target_status NOT IN ('pending', 'running') THEN
        RAISE EXCEPTION 'observations for terminal scan % are immutable', target_scan_id;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.scan_run_id <> NEW.scan_run_id THEN
        RAISE EXCEPTION 'an observation cannot be moved between scan runs';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER scan_observations_open_run_only
    BEFORE INSERT OR UPDATE OR DELETE ON scan_observations
    FOR EACH ROW EXECUTE FUNCTION prevent_closed_scan_observation_mutation();

CREATE FUNCTION prevent_scan_run_reopen()
RETURNS trigger
LANGUAGE plpgsql
AS $
BEGIN
    IF OLD.status IN ('complete', 'partial', 'failed', 'cancelled')
       AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'terminal scan runs cannot change status';
    END IF;
    IF OLD.status = 'pending' AND NEW.status NOT IN ('pending', 'running', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'invalid scan status transition: % -> %', OLD.status, NEW.status;
    END IF;
    IF OLD.status = 'running'
       AND NEW.status NOT IN ('running', 'complete', 'partial', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'invalid scan status transition: % -> %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$;

CREATE TRIGGER scan_runs_valid_transitions
    BEFORE UPDATE OF status ON scan_runs
    FOR EACH ROW EXECUTE FUNCTION prevent_scan_run_reopen();

-- The only built-in operation that marks unseen locations missing.
-- It refuses partial, failed, cancelled, pending, or running scans.
CREATE FUNCTION reconcile_missing_asset_locations(p_scan_run_id uuid)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_root_id uuid;
    v_finished_at timestamptz;
    v_event_count bigint;
BEGIN
    SELECT storage_root_id, finished_at
      INTO v_root_id, v_finished_at
      FROM scan_runs
     WHERE id = p_scan_run_id
       AND status = 'complete'
       AND finished_at IS NOT NULL
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation requires a completed scan run: %', p_scan_run_id;
    END IF;

    WITH observed_files AS (
        SELECT
            l.id AS location_id,
            l.availability AS old_availability,
            CASE WHEN o.is_excluded THEN 'excluded' ELSE 'present' END AS new_availability
        FROM asset_locations AS l
        JOIN scan_observations AS o
          ON o.scan_run_id = p_scan_run_id
         AND o.normalized_path_key = l.normalized_path_key
         AND o.path_normalizer_version = l.path_normalizer_version
         AND o.entry_kind = 'file'
        WHERE l.storage_root_id = v_root_id
          AND l.valid_to IS NULL
    ),
    refreshed AS (
        UPDATE asset_locations AS l
           SET availability = o.new_availability,
               last_seen_at = v_finished_at
          FROM observed_files AS o
         WHERE l.id = o.location_id
        RETURNING l.id, o.old_availability, l.availability AS new_availability
    ),
    missing_candidates AS (
        SELECT l.id, l.availability AS old_availability
          FROM asset_locations AS l
         WHERE l.storage_root_id = v_root_id
           AND l.valid_to IS NULL
           AND l.availability IN ('present', 'excluded')
           AND NOT EXISTS (
               SELECT 1
                 FROM scan_observations AS o
                WHERE o.scan_run_id = p_scan_run_id
                  AND o.normalized_path_key = l.normalized_path_key
                  AND o.path_normalizer_version = l.path_normalizer_version
                  AND o.entry_kind = 'file'
           )
    ),
    marked_missing AS (
        UPDATE asset_locations AS l
           SET availability = 'missing'
          FROM missing_candidates AS m
         WHERE l.id = m.id
        RETURNING l.id, m.old_availability, l.availability AS new_availability
    ),
    state_changes AS (
        SELECT id, old_availability, new_availability
          FROM refreshed
         WHERE old_availability IS DISTINCT FROM new_availability
        UNION ALL
        SELECT id, old_availability, new_availability
          FROM marked_missing
    )
    INSERT INTO asset_location_events (
        id,
        asset_location_id,
        scan_run_id,
        event_type,
        previous_availability,
        new_availability,
        occurred_at
    )
    SELECT
        gen_random_uuid(),
        id,
        p_scan_run_id,
        'availability_changed',
        old_availability,
        new_availability,
        v_finished_at
    FROM state_changes;

    GET DIAGNOSTICS v_event_count = ROW_COUNT;
    RETURN v_event_count;
END;
$$;

COMMENT ON FUNCTION reconcile_missing_asset_locations(uuid) IS
    'Only COMPLETE scans may reconcile unseen paths to MISSING; run inside the scan finalization transaction.';
