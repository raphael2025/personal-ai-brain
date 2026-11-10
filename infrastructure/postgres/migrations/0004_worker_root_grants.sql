-- Workers receive explicit, revocable read access to individual storage roots.
-- Host-specific mount paths remain in worker-local configuration, never in this table.

CREATE TABLE worker_root_grants (
    worker_id uuid NOT NULL REFERENCES workers(id) ON DELETE RESTRICT,
    storage_root_id uuid NOT NULL REFERENCES storage_roots(id) ON DELETE RESTRICT,
    permission text NOT NULL CHECK (permission = 'read_source'),
    granted_by text NOT NULL CHECK (length(btrim(granted_by)) BETWEEN 1 AND 200),
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    revoked_by text,
    PRIMARY KEY (worker_id, storage_root_id, permission),
    CHECK (
        (revoked_at IS NULL AND revoked_by IS NULL)
        OR
        (revoked_at IS NOT NULL AND revoked_by IS NOT NULL
            AND length(btrim(revoked_by)) BETWEEN 1 AND 200)
    )
);

CREATE INDEX worker_root_grants_active_idx
    ON worker_root_grants (worker_id, storage_root_id)
    WHERE revoked_at IS NULL;
