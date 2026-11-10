-- Explicit memory lifecycle with immutable source evidence and append-only transitions.
-- Model inference is always a candidate until an explicit user confirmation.

CREATE TABLE memories (
    id uuid PRIMARY KEY,
    content text NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 20000),
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    origin text NOT NULL CHECK (
        origin IN ('user_authored', 'user_confirmed', 'source_derived', 'model_inferred')
    ),
    state text NOT NULL CHECK (
        state IN ('candidate', 'active', 'stale', 'conflicted', 'rejected', 'archived')
    ),
    confidence double precision CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    created_by text NOT NULL CHECK (length(btrim(created_by)) BETWEEN 1 AND 200),
    confirmed_by text CHECK (confirmed_by IS NULL OR length(btrim(confirmed_by)) BETWEEN 1 AND 200),
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (origin = 'user_confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
        OR
        (origin <> 'user_confirmed' AND confirmed_by IS NULL AND confirmed_at IS NULL)
    ),
    CHECK (origin <> 'model_inferred' OR state IN ('candidate', 'rejected', 'archived')),
    CHECK (origin <> 'source_derived' OR state = 'candidate')
);

CREATE INDEX memories_state_updated_idx ON memories (state, updated_at DESC);
CREATE INDEX memories_origin_state_idx ON memories (origin, state);

-- Composite target key prevents attaching an artifact produced from another source version.
CREATE UNIQUE INDEX processing_artifacts_id_version_uq
    ON processing_artifacts (id, asset_version_id);

CREATE TABLE memory_evidence (
    memory_id uuid NOT NULL REFERENCES memories(id) ON DELETE RESTRICT,
    asset_version_id uuid NOT NULL REFERENCES asset_versions(id) ON DELETE RESTRICT,
    artifact_id uuid,
    locator text NOT NULL CHECK (length(btrim(locator)) BETWEEN 1 AND 1000),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (memory_id, asset_version_id, locator),
    FOREIGN KEY (artifact_id, asset_version_id)
        REFERENCES processing_artifacts(id, asset_version_id) ON DELETE RESTRICT
);

CREATE INDEX memory_evidence_asset_version_idx ON memory_evidence (asset_version_id);
CREATE INDEX memory_evidence_artifact_idx ON memory_evidence (artifact_id) WHERE artifact_id IS NOT NULL;

CREATE TABLE memory_state_events (
    id uuid PRIMARY KEY,
    memory_id uuid NOT NULL REFERENCES memories(id) ON DELETE RESTRICT,
    actor text NOT NULL CHECK (length(btrim(actor)) BETWEEN 1 AND 200),
    action text NOT NULL CHECK (action IN ('created', 'transitioned', 'confirmed')),
    previous_state text CHECK (
        previous_state IS NULL OR previous_state IN ('candidate', 'active', 'stale', 'conflicted', 'rejected', 'archived')
    ),
    new_state text NOT NULL CHECK (
        new_state IN ('candidate', 'active', 'stale', 'conflicted', 'rejected', 'archived')
    ),
    previous_origin text CHECK (
        previous_origin IS NULL OR previous_origin IN ('user_authored', 'user_confirmed', 'source_derived', 'model_inferred')
    ),
    new_origin text NOT NULL CHECK (
        new_origin IN ('user_authored', 'user_confirmed', 'source_derived', 'model_inferred')
    ),
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (action = 'created' AND previous_state IS NULL AND previous_origin IS NULL)
        OR (action IN ('transitioned', 'confirmed') AND previous_state IS NOT NULL AND previous_origin IS NOT NULL)
    )
);

CREATE INDEX memory_state_events_memory_idx ON memory_state_events (memory_id, occurred_at, id);

CREATE FUNCTION prevent_memory_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'memory evidence and state events are append-only';
END;
$function$;

CREATE TRIGGER memory_evidence_immutable
    BEFORE UPDATE OR DELETE ON memory_evidence
    FOR EACH ROW EXECUTE FUNCTION prevent_memory_history_mutation();

CREATE TRIGGER memory_state_events_immutable
    BEFORE UPDATE OR DELETE ON memory_state_events
    FOR EACH ROW EXECUTE FUNCTION prevent_memory_history_mutation();
