# Explicit Memory Lifecycle v1\n\n**Status:** initial domain and PostgreSQL repository implementation; not yet a complete memory or context system.\n\n## Origins and trust\n\n- `user_authored`: directly entered by the user. It may be created as a candidate or active note.
- `source_derived`: extracted from a specific immutable asset version. It must include at least one evidence reference and always starts as a candidate.
- `model_inferred`: proposed by a model. It always starts as a candidate and cannot become active through an ordinary state transition.
- `user_confirmed`: provenance assigned only by the explicit confirmation operation. Confirmation records the actor and time and promotes a candidate to active.

An actor string is audit metadata, not authentication. The current repository does not establish that a caller is a human; authenticated principals and authorization are part of the separate policy-engine milestone. Do not expose confirmation through an unauthenticated API.

## States

`candidate`, `active`, `stale`, `conflicted`, `rejected`, and `archived` are explicit lifecycle states. Terminal `archived` memories cannot be reactivated. Conflicts remain separate records; this version does not merge or overwrite competing claims.

Allowed transitions:

| From | To |
|---|---|
| candidate | active (user-authored only), rejected, archived |
| active | stale, conflicted, archived |
| stale | active, conflicted, rejected, archived |
| conflicted | active, stale, rejected, archived |
| rejected | archived |
| archived | none |

Only `confirm()` can promote an inferred or source-derived candidate to active, and it changes the origin to `user_confirmed`. Source-derived memories retain links to exact asset versions and optional artifacts.

## Persistence guarantees

- Content SHA-256 is recorded at creation.
- Evidence links reference immutable asset versions; optional artifact references are constrained to the same source version.
- Evidence links and state-transition events are append-only.
- Create, evidence insertion, and initial audit event share one transaction.
- State transition and audit event share one transaction and lock the memory row.
- The repository has no update/delete operation for memory content in v1. A future revision model must preserve prior content and evidence rather than silently overwrite it.

Apply migration `0005_memory_lifecycle.sql` after migration `0001_asset_registry.sql` (or after the full existing migration sequence). PostgreSQL is required for repository integration tests.

## Deliberate non-goals

No automatic promotion, hidden preference inference, memory ranking/activation decay, conflict resolution, semantic deduplication, ContextBundle assembly, provider egress, or authenticated user interface is included. Model output and source-derived facts remain candidates until explicit review.
