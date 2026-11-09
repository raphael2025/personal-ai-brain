# Module Contracts v1

**Status:** proposed implementation contracts; not runtime feature claims.

## Target package layout

    src/personal_ai_brain/
      api/             HTTP routes, OpenAPI, auth dependencies
      assets/          identity, roots, locations, scans
      ingestion/       jobs, leases, attempts, artifact publication
      extractors/      isolated format adapters
      knowledge/       chunks, entities, claims, relations
      memory/          explicit memories, lifecycle, conflicts
      retrieval/       query plan, candidate channels, ranking
      context/         policy-filtered ContextBundle assembly
      policy/          principals, scopes, classification, egress
      provenance/      source references and transformation lineage
      audit/            append-only access and administrative events
      connectors/      MCP, filesystem, NAS, model providers
      workers/         worker runtime and task registry
      storage/         repository protocols and adapters
      evaluation/      datasets, metrics, regression harness

## Dependency direction

Allowed: API/CLI/MCP → application services → domain contracts; worker adapters → extractor contracts; storage adapters → repository protocols; Context Manager → policy + retrieval + provenance + budget.

Forbidden:
- Domain models importing API frameworks or ORM models.
- Extractors writing directly into production tables.
- Retrieval bypassing policy to load arbitrary files.
- External model adapters accessing source roots or database credentials.
- Workers mutating originals.
- Memory summaries replacing source evidence.

## Core ports

### AssetRepository
- register_root(root_spec, actor) → StorageRoot
- begin_scan(root_id, scope, actor) → ScanRun
- record_observation(scan_id, observation) → None
- complete_scan(scan_id, outcome) → ScanSummary
- get_asset(asset_id) → Asset or None
- list_asset_versions(asset_id) → sequence of AssetVersion
- reconcile(scan_id) → ReconciliationResult

Invariant: reconcile accepts only COMPLETE scans and is idempotent per scan ID.

### DiscoveryAdapter
- discover(root, scope, cancellation) → stream of DiscoveryEvent
- Event variants: RootUnavailable, EntryObserved, EntrySkipped, EntryError, ScanWarning.
- Never follow symlinks by default or modify source data.
- Distinguish empty directory from inaccessible/unavailable root.

### JobRepository and WorkerRuntime
- enqueue(spec, idempotency_key) → Job
- claim(worker_id, capabilities, lease_ttl) → JobLease or None
- heartbeat(lease_id) → LeaseStatus
- publish_artifact(lease_id, manifest) → Artifact
- fail(lease_id, error, retryable) → JobState
- acknowledge_cancel(lease_id) → JobState

A lease is fenced by a monotonically increasing generation. A superseded worker cannot publish.

### Extractor
- manifest() → ExtractorManifest
- extract(source_ref, options, output_sink) → ExtractionResult

Manifest records name/version, supported MIME/types, resource profile, required permissions, network requirement, and license. Extractors receive read-only source handles and write only to isolated output sinks.

### ArtifactStore
- put(artifact, idempotency_key) → ArtifactRef
- get(artifact_ref) → byte stream
- delete_derived(artifact_ref, actor, reason) → Tombstone

Only derived artifacts may be deleted through this port.

### RetrievalProvider
- search(query_plan, allowed_resource_ids, limit) → candidates
- Candidate includes resource/version/chunk IDs, channel, raw score, and diagnostics.
- Provider must not return unauthorized content; Context Manager independently verifies policy before expansion.

### PolicyEngine
- authorize(principal, action, resource, purpose) → Decision
- Decision is ALLOW or DENY with policy version, matched rules, reason code.
- Unknown principal, missing purpose, policy outage, and evaluation error resolve to DENY.

### ContextAssembler
- assemble(request, principal) → ContextBundle
- Authorize before expansion, enforce budget, preserve evidence IDs, record omissions, and audit.
- Never call a model provider. Model invocation is a separate egress-authorized connector action.

## Shared conventions

- IDs are opaque UUID/ULID values, never derived from absolute paths.
- Timestamps are UTC RFC 3339; sizes are integer bytes.
- Enums are validated at boundaries.
- Errors use stable machine-readable codes and safe messages.
- Every mutation accepts an actor and emits an audit event.
- Repository methods are transaction-scoped; domain objects do not perform hidden network calls.
- Large collections use cursor pagination.
- Retryable writes accept idempotency keys.

## Error taxonomy

| Code | Meaning | Retry |
|---|---|---|
| ROOT_UNAVAILABLE | Volume/share unavailable | Later |
| PERMISSION_DENIED | Caller/worker lacks access | No, unless policy changes |
| ENTRY_CHANGED_DURING_READ | Source changed during processing | After rediscovery |
| UNSUPPORTED_FORMAT | No extractor available | No |
| EXTRACTOR_TIMEOUT | Resource/time limit exceeded | Bounded |
| EXTRACTOR_CRASH | Worker/extractor failed | Bounded |
| LEASE_LOST | Worker lost ownership | Discard output |
| POLICY_DENIED | Resource unauthorized | No |
| SOURCE_VERSION_STALE | Source changed after enqueue | Re-enqueue |
| ARTIFACT_CORRUPT | Output failed validation | Bounded then quarantine |

## Adapter test contract

Every adapter needs shared protocol tests, happy/error paths, idempotency/retry tests, lease/concurrency tests where relevant, synthetic fixtures, deterministic clocks/IDs, and no network access unless explicitly part of that adapter.
