# Implementation Map and Contributor Work Packages

This is the execution map for turning the architecture into a working product. Implement each work package as focused PRs with tests. Dependencies are deliberate; do not build UI on unstable contracts.

## A — Asset Registry (P0) — [Issue #32](https://github.com/raphael2025/personal-ai-brain/issues/32) (initial repository/service/root-scan path merged in PR #34), [Issue #35](https://github.com/raphael2025/personal-ai-brain/issues/35) (remaining CLI/dry-run/normalizer migration), [Issue #10](https://github.com/raphael2025/personal-ai-brain/issues/10) (schema merged), [Issue #1](https://github.com/raphael2025/personal-ai-brain/issues/1) (domain models merged)

Goal: know which assets exist, where they are, and which versions were observed.

Merged foundation: PostgreSQL schema; repository/service for root enrollment, file identity/version/location persistence, scan observations, and COMPLETE-only reconciliation; root add/list and scan CLI; descriptor-relative hashing. Remaining: scan status, asset list/inspect, dry-run reconciliation, explicit normalizer migration, crash recovery, rename/duplicate candidate workflow, and migration/rollback tooling.

Acceptance: identical finalization replay is idempotent and conflicting replay is rejected; partial/failed scans never mark missing; identical bytes at different paths remain separate pending resolution; sources never modified. A 100k synthetic-entry benchmark and explicit normalizer migration remain outstanding.

## B — Durable Jobs and Workers (P0) — [Issue #21](https://github.com/raphael2025/personal-ai-brain/issues/21)

Delivered in PRs #38–#39: job/attempt/lease schema, fencing and heartbeat, worker registration/capability matching, retry/backoff/cancellation, and pull-based runtime. PR #44 adds PostgreSQL JSONB artifact publication fenced by the active lease and idempotent by source/processor/config identity. PR #45 adds revocable worker/root read grants, audited grant/revoke, worker-local TOML mount mapping, active job-lease verification during source resolution, bounded descriptor-relative no-follow reads, and immutable SHA-256 verification. PR #46 adds worker registration/grant/revoke/run CLI, extraction enqueue, a built-in text handler, foreground signal drain, and an end-to-end PostgreSQL pipeline test. Remaining: OS sandboxing, per-worker DB credentials, service supervision, external content-addressed staging/blob publication, orphan cleanup, and crash/recovery drills.

Acceptance: kill worker mid-job and prove lease recovery; stale lease cannot publish an artifact; duplicate enqueue/publication is idempotent; retry budget deterministic. Database publication fencing is covered; external blob publication and process-level recovery remain unverified.

## C — Extraction and Provenance (P1) — [Issue #22](https://github.com/raphael2025/personal-ai-brain/issues/22)

PR #46 wires the bounded text/Markdown/code extractor end-to-end: durable job enqueue, root-granted active-lease source resolution, descriptor-relative read and SHA verification, extraction, fenced artifact publication, and job completion. PR #44 persists output and source provenance in PostgreSQL. Remaining: external artifact store/rebuild manifests, PDF/DOCX/HTML, and image/audio/video adapters. Apply file-size, CPU, memory, time, and archive expansion limits.

Acceptance: malformed/adversarial synthetic corpus; unsupported types explicitly reported; same source+extractor+config idempotent; source never modified.

## D — Search and Evaluation (P1) — [Issue #23](https://github.com/raphael2025/personal-ai-brain/issues/23); technology review: [evaluation report](../research/technology-evaluation-2026-11.md)

Initial baseline merged in PR #43: dependency-free in-memory BM25, Unicode tokenization, deterministic tie-breaking, root/type/time filters, and a reproducible synthetic benchmark. Remaining: expand the small four-document/five-question corpus, integrate persisted chunks and immutable source-version provenance, add evidence spans/citations, then compare optional vector/hybrid channels against the lexical baseline.

Acceptance: report Recall@5/10, MRR, nDCG@10, citation precision, P50/P95 latency with dataset/hardware/versions/config. The initial synthetic smoke benchmark is implemented; production evaluation remains blocked on a larger labelled corpus and persistent chunk/version provenance. Compare every ranker against lexical baseline; no unmeasured quality claims.

## E — Knowledge and Memory (P2) — [Issue #24](https://github.com/raphael2025/personal-ai-brain/issues/24)

Deliver L0/L1/L2 schemas; entity/claim/evidence model; explicit memory CRUD/provenance; origin types; freshness/conflict/stale/archive states; activation independent from depth.

Acceptance: inference cannot become user preference without confirmation; conflicts preserved; factual results have evidence or explicit unsupported status; deletion invalidates caches/indexes.

## F — Context Manager and Policy (P2) — [Issue #25](https://github.com/raphael2025/personal-ai-brain/issues/25)

Deliver principals/scopes/classifications; deny-by-default policy engine; context budgeter/progressive expansion; citation map/omission reasons; append-only audit; egress approval/revocation.

Acceptance: denied resource never reaches client; policy outage fails closed; cache scoped by principal/policy version; egress disabled absent scoped grant; prompt-injection and provider-mismatch tests.

## G — API, MCP, and UI (P3)

Deliver versioned local HTTP API/OpenAPI; CLI; read-only MCP tools first; desktop/local web UI for status, approvals, evidence. Mutating MCP tools require explicit confirmation.

Acceptance: API/MCP share application services and policy; no connector bypass; local-only bind default; factual results include evidence references.

## H — Multi-node Operations (P3) — [Issue #27](https://github.com/raphael2025/personal-ai-brain/issues/27)

Deliver outbound worker polling; capability-aware queues; encrypted transport and worker identity; backup/restore; offline recovery; metrics and redacted logs.

Acceptance: control-node reboot preserves registry/jobs; worker disconnect does not corrupt state; restore drill passes; no public worker listener.

## Priority for contributors

| Priority | Package | Good first PR |
|---|---|---|
| P0 | Registry services | CRUD/service tests |
| P0 | Job/lease model | schema + state machine |
| P1 | Extractors | one isolated extractor |
| P1 | Evaluation corpus | synthetic docs + labelled queries |
| P1 | Lexical retrieval | BM25 adapter + benchmark |
| P2 | Memory lifecycle | domain model + transition tests |
| P2 | Policy engine | deny-by-default evaluator |
| P3 | MCP adapter | read-only tools over stable services |
| P3 | UI | only after API contracts stabilize |

## Definition of done

Each package needs an issue with scope/dependencies/acceptance; contract and failure tests; reversible migration or documented forward-only policy; passing CI; updated docs/status; synthetic fixtures only; security/privacy review.
