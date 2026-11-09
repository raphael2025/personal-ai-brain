# System Blueprint v1

**Status:** normative target architecture proposal. The repository is pre-alpha. This document defines intended behavior, not implemented functionality. Security-boundary changes require an ADR.

## 1. Product contract

Personal AI Brain (PAB) is local-first personal knowledge infrastructure. It inventories user-controlled digital assets, derives searchable representations, manages explicit memories, and supplies permission-filtered evidence to AI clients.

MUST:
1. Preserve originals in place; source files remain authoritative.
2. Separate asset identity, storage location, and availability.
3. Support disconnected NAS/removable volumes without interpreting them as empty.
4. Make derived artifacts traceable to immutable source versions and processing versions.
5. Make workers idempotent, resumable, bounded, and observable.
6. Deny external data egress unless an explicit scoped policy permits it.
7. Return evidence, provenance, freshness, and uncertainty with factual results.
8. Rebuild derived indexes from source records and versioned processing manifests.

MUST NOT silently rewrite source files, use a path as identity, treat embeddings as facts, or infer deletion from an incomplete scan.

## 2. System context and data flow

The logical flow is:

User / CLI / Desktop / AI client
→ Local API or MCP adapter
→ Authentication and Context Manager
→ Policy Engine
→ Query Planner and Retrieval
→ Evidence expansion and ContextBundle
→ Approved client or explicitly approved model gateway

In parallel:

Storage roots → Discovery workers → Asset Registry → Durable job queue
→ Ingestion workers → Versioned artifacts → Knowledge store and indexes
→ Retrieval providers

Audit receives access decisions and mutations from all application services.

## 3. Runtime planes

| Plane | Responsibilities | Boundary |
|---|---|---|
| Control | API, registry, policy, scheduler, jobs, audit | Trusted local service; authenticated clients |
| Data | discovery, parsing, OCR, transcription, embedding | Isolated workers; untrusted input |
| Retrieval | lexical/vector/metadata/temporal search, ranking | Read-only; policy-filtered |
| Client | CLI, desktop, MCP, AI connectors | Untrusted callers; explicit scopes |
| Storage | originals, database, artifacts, backups | Separate availability and backup domains |

Initial deployment is a modular monolith with independently runnable workers. Do not split into microservices without measured operational need.

## 4. Canonical domains

- **Asset Registry:** storage roots, stable asset IDs, versions, locations, scan observations, identity resolution.
- **Ingestion:** jobs, attempts, leases, extractor manifests, artifact publication.
- **Knowledge:** chunks, entities, relations, claims, summaries, evidence links.
- **Memory:** user-authored/confirmed memories, source-derived claims, inferred candidates, conflicts, lifecycle.
- **Retrieval:** query planning, candidate channels, ranking, evidence assembly, evaluation.
- **Context Manager:** caller identity, purpose, permissions, progressive expansion, token budget, citations.
- **Policy & Audit:** principals, scopes, classifications, egress grants, append-only events.
- **Connectors:** filesystems, NAS, MCP, local/external model gateways, AI clients.

Domain logic must not depend on FastAPI, SQLAlchemy, a vector database, or vendor-specific model SDKs. Adapters implement ports.

## 5. Core entity model

StorageRoot 1—N AssetLocation; Asset 1—N AssetVersion; Asset 1—N AssetLocation; ScanRun 1—N ScanObservation; AssetVersion 1—N ProcessingJob; ProcessingJob 1—N ProcessingArtifact; AssetVersion 1—N ContentChunk; Claim 1—N ClaimEvidence; Memory 1—N MemoryEvidence; Principal 1—N AccessEvent.

- asset_id is an opaque stable internal ID, never a path or content hash.
- Location is a time-varying observation, not identity.
- Fingerprints support matching but do not authorize automatic logical-asset merging.
- Identical bytes at two paths may represent independent copies; preserve both until an explicit resolution.
- Rename is a candidate relationship with history, not destructive replacement.
- Only a COMPLETE scan of the same root and scope may reconcile missing locations.
- PARTIAL, FAILED, cancelled, or unavailable-root scans must never mark assets missing.

## 6. Ingestion state machine

QUEUED → LEASED → RUNNING → SUCCEEDED
RUNNING → RETRY_WAIT → QUEUED (retryable failure)
RUNNING → FAILED (terminal failure)
LEASED → RETRY_WAIT (lease expiry)
QUEUED / LEASED → CANCELLED
RUNNING → CANCEL_REQUESTED → CANCELLED

Idempotency key = source version + task type + extractor semantic version + configuration digest. Leases are time-bounded and fenced by a monotonically increasing generation. A stale worker cannot publish. Workers heartbeat, write to isolated temporary output, validate, then atomically publish artifact metadata. Retries use bounded exponential backoff with jitter. Poison jobs cannot block unrelated work.

## 7. Progressive knowledge

Content depth and activation temperature are independent axes.

| Depth | Contract | Typical payload |
|---|---|---|
| L0 | Cheap relevance decision | identity, title, type, compact abstract, dates, tags |
| L1 | Navigable understanding | outline, entities, claims, summary, chunk references |
| L2 | Verifiable evidence | source spans, extracted full text, original location |

| Temperature | Runtime behavior |
|---|---|
| Hot | eligible for short-lived low-latency cache/prefetch |
| Warm | indexed and ranked normally |
| Cold | retained, not routinely expanded; activated on demand |

Not every asset needs all depths. Cold does not mean deleted. Activation changes retrieval priority, not source authority.

## 8. Retrieval and evidence contract

1. Parse intent, entities, time constraints, desired depth, and caller scope.
2. Apply access policy before reading protected content.
3. Generate candidates from lexical/BM25, vector, metadata, temporal, and graph channels where available.
4. Deduplicate by evidence identity while retaining independent sources.
5. Rank and expose channel contributions for diagnostics.
6. Expand L0 to L1/L2 only within the caller budget.
7. Return claims with source/version/span, freshness, confidence, and conflicts.
8. Audit the request and policy decision.

Semantic similarity is not proof. Missing evidence and unresolved conflicts must be explicit.

## 9. ContextBundle contract

A ContextBundle includes request ID, principal, purpose, creation time, policy version, allowed scopes, query interpretation, retrieval plan, ordered evidence with provenance, conflicts/uncertainty, omitted items and reasons, token/byte budget, citation map, and expiry.

The Context Manager must not include resources with DENY or UNKNOWN policy decisions. External model adapters receive only a serialized bundle approved for that destination; they never receive direct database or filesystem access.

## 10. Target API

All routes are versioned under /v1. Initial routes are read-only except explicit enrollment and memory operations.

| Route | Method | Purpose |
|---|---|---|
| /health | GET | readiness without sensitive details |
| /storage-roots | GET/POST | list/enroll roots; enrollment is explicit |
| /storage-roots/{id}/scans | GET/POST | inspect/start scan |
| /assets/{id} | GET | metadata and locations |
| /assets/{id}/versions | GET | version history |
| /jobs/{id} | GET/POST | inspect, retry, cancel |
| /search | POST | authorized evidence search |
| /memories | GET/POST | list/create explicit memories |
| /memories/{id} | GET/PATCH/DELETE | user-controlled lifecycle |
| /context/assemble | POST | policy-filtered ContextBundle |
| /audit/events | GET | authorized audit inspection |

These routes are design targets, not implemented endpoints. OpenAPI and contract tests are required with the first API implementation.

## 11. Deployment topology

Target:
- Always-on control node: PostgreSQL, API, registry, scheduler/queue, policy, audit, lightweight retrieval.
- Compute node(s): parsing, OCR, transcription, embeddings, local inference.
- Source storage: Windows volumes, WSL paths, NAS, removable disks.
- Optional model gateway: external provider, disabled by default and isolated behind egress policy.

Workers pull jobs outbound; do not expose worker ports publicly. A disconnected source is unavailable, not empty. Worker loss leaves leases to expire and be reclaimed.

## 12. Security invariants

- Default bind is loopback until authentication and authorization exist.
- Never expose unauthenticated API, MCP, parser, or worker endpoints to LAN/WAN.
- Parser workers require CPU, memory, time, file-size, archive-expansion limits, and isolated temp directories.
- Treat document text, OCR, metadata, code comments, tool output, and model output as untrusted data and possible prompt injection.
- External egress is denied unless a user-approved grant specifies provider, purpose, data class, scope, and expiry.
- Secrets are runtime-only. Logs redact source paths and content.
- Audit access decisions, not full sensitive payloads.
- Backup/restore must cover database, policy, keys, and artifact indexes; originals remain independently backed up.

## 13. Observability

Every request and job carries correlation IDs. Measure queue depth/age, lease expiry, retries, extractor duration/failure, scan completeness, source availability, index freshness, retrieval latency, citation coverage, policy denials, and egress attempts. Logs are structured and redact content by default.

## 14. Delivery order

1. Registry and safe scan reconciliation.
2. Durable jobs, leases, and worker runner.
3. Text extraction and provenance storage.
4. Lexical retrieval and labelled evaluation set.
5. Embedding retrieval and hybrid ranking after baseline measurement.
6. L0/L1/L2 and explicit memory lifecycle.
7. Policy-enforced ContextBundle and read-only API.
8. MCP adapter.
9. Multi-node operations, backup/restore, security review.

Do not begin with a graph database, large model, or microservice fleet. Prove identity, provenance, authorization, and recovery first.

## 15. Definition of done

A capability is done only when its contract and failure modes are documented, implementation and tests are merged, migration/rollback is documented, CI passes, security/privacy review is recorded, recovery is demonstrated, and status distinguishes implemented from proposed.
