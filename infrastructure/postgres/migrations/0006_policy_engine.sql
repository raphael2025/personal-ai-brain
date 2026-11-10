-- Deny-by-default principals, scoped grants, policy versioning, and redacted audit.
CREATE TABLE policy_state (
    singleton boolean PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO policy_state (singleton, version) VALUES (TRUE, 1);

CREATE TABLE policy_principals (
    id uuid PRIMARY KEY,
    principal_kind text NOT NULL CHECK (
        principal_kind IN ('user', 'ai_client', 'worker', 'service', 'provider')
    ),
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    scopes text[] NOT NULL DEFAULT '{}',
    enabled boolean NOT NULL DEFAULT TRUE,
    owner_principal_id uuid REFERENCES policy_principals(id) ON DELETE RESTRICT,
    created_by text NOT NULL CHECK (length(btrim(created_by)) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (array_position(scopes, '') IS NULL AND array_position(scopes, NULL) IS NULL)
);

CREATE INDEX policy_principals_enabled_idx
    ON policy_principals (id) WHERE enabled = TRUE;

CREATE TABLE policy_grants (
    id uuid PRIMARY KEY,
    principal_id uuid NOT NULL REFERENCES policy_principals(id) ON DELETE RESTRICT,
    actions text[] NOT NULL,
    purposes text[] NOT NULL,
    classifications text[] NOT NULL,
    resource_ids uuid[] NOT NULL DEFAULT '{}',
    root_ids uuid[] NOT NULL DEFAULT '{}',
    provider_id text,
    expires_at timestamptz,
    revoked_at timestamptz,
    revoked_by text,
    created_by text NOT NULL CHECK (length(btrim(created_by)) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(actions) > 0),
    CHECK (
        actions <@ ARRAY['read_metadata', 'read_content', 'search', 'memory_confirm', 'egress']::text[]
        AND array_position(actions, NULL) IS NULL
    ),
    CHECK (
        cardinality(purposes) > 0
        AND array_position(purposes, '') IS NULL
        AND array_position(purposes, NULL) IS NULL
    ),
    CHECK (cardinality(classifications) > 0),
    CHECK (
        classifications <@ ARRAY['public', 'personal', 'sensitive', 'restricted']::text[]
        AND array_position(classifications, NULL) IS NULL
    ),
    CHECK (
        (cardinality(resource_ids) > 0 OR cardinality(root_ids) > 0)
        AND array_position(resource_ids, NULL) IS NULL
        AND array_position(root_ids, NULL) IS NULL
    ),
    CHECK (
        (actions = ARRAY['egress']::text[] AND provider_id IS NOT NULL
            AND length(btrim(provider_id)) BETWEEN 1 AND 200)
        OR
        ('egress' <> ALL(actions) AND provider_id IS NULL)
    ),
    CHECK (
        (revoked_at IS NULL AND revoked_by IS NULL)
        OR
        (revoked_at IS NOT NULL AND revoked_by IS NOT NULL
            AND length(btrim(revoked_by)) BETWEEN 1 AND 200)
    )
);

CREATE INDEX policy_grants_principal_idx ON policy_grants (principal_id);
CREATE INDEX policy_grants_active_idx
    ON policy_grants (principal_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE policy_decisions (
    request_id uuid PRIMARY KEY,
    principal_id uuid,
    action text NOT NULL CHECK (length(action) BETWEEN 1 AND 64),
    resource_type text,
    resource_id uuid,
    root_id uuid,
    classification text CHECK (
        classification IS NULL OR classification IN ('public', 'personal', 'sensitive', 'restricted')
    ),
    purpose text,
    destination_provider_id text,
    decision text NOT NULL CHECK (decision IN ('allow', 'deny')),
    reason_code text NOT NULL,
    policy_version bigint NOT NULL CHECK (policy_version >= 0),
    matched_grant_id uuid,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX policy_decisions_principal_time_idx
    ON policy_decisions (principal_id, occurred_at DESC);
CREATE INDEX policy_decisions_resource_time_idx
    ON policy_decisions (resource_id, occurred_at DESC);

CREATE TABLE policy_admin_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor text NOT NULL CHECK (length(btrim(actor)) BETWEEN 1 AND 200),
    action text NOT NULL CHECK (
        action IN ('principal_registered', 'principal_enabled', 'principal_disabled', 'grant_created', 'grant_revoked')
    ),
    target_type text NOT NULL CHECK (target_type IN ('principal', 'policy_grant')),
    target_id uuid NOT NULL,
    policy_version bigint NOT NULL CHECK (policy_version >= 1),
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX policy_admin_events_time_idx ON policy_admin_events (occurred_at DESC);

CREATE FUNCTION prevent_policy_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'policy audit records are append-only';
END;
$function$;

CREATE TRIGGER policy_decisions_immutable
    BEFORE UPDATE OR DELETE ON policy_decisions
    FOR EACH ROW EXECUTE FUNCTION prevent_policy_audit_mutation();

CREATE TRIGGER policy_admin_events_immutable
    BEFORE UPDATE OR DELETE ON policy_admin_events
    FOR EACH ROW EXECUTE FUNCTION prevent_policy_audit_mutation();
