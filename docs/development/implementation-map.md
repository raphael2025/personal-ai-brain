# Implementation Map and Contributor Work Packages

This is the execution map for turning the architecture into a working product. Implement each work package as focused PRs with tests. Dependencies are deliberate; do not build UI on unstable contracts.

## A — Asset Registry (P0) — [Issue #32](https://github.com/raphael2025/personal-ai-brain/issues/32) (services/CLI), [Issue #10](https://github.com/raphael2025/personal-ai-brain/issues/10) (schema merged), [Issue #1](https://github.com/raphael2025/personal-ai-brain/issues/1) (domain models merged)

Goal: know which assets exist, where they are, and which versions were observed.

Deliver: finish/validate PostgreSQL migrations; repository/service layer for roots/assets/versions/locations/scans; transactional scan completion and reconciliation; offline/partial semantics; rename/duplicate candidate workflow; CLI for root enrollment, scan, list, inspect; migration/rollback tests.

Acceptance: repeated scan idempotent; partial/failed/offline scans never mark missing; identical bytes at different paths remain separate pending resolution; sources never modified; 100k synthetic-entry benchmark reports hardware/time/memory.

## B — Durable Jobs and Workers (P0) — [Issue #21](https://github.com/raphael2025/personal-ai-brain/issues/21)

Deliver: job/attempt/lease schema; lease fencing and heartbeat; worker registration/capability matching; retry/backoff/cancellation/poison handling; temporary artifact writes and atomic publication; worker CLI.

Acceptance: kill worker mid-job and prove lease recovery; stale lease cannot publish; duplicate enqueue does not duplicate logical work; retry budget deterministic.

## C — Extraction and Provenance (P1) — [Issue #22](https://github.com/raphael2025/personal-ai-brain/issues/22)

Initial extractors: text/Markdown, PDF, DOCX, HTML, source code; then image metadata/OCR and audio/video metadata/transcription. Every artifact records source version, extractor version, config digest, schema version, checksum, timestamps. Apply file-size, CPU, memory, time, and archive expansion limits.

Acceptance: malformed/adversarial synthetic corpus; unsupported types explicitly reported; same source+extractor+config idempotent; source never modified.

## D — Search and Evaluation (P1) — [Issue #23](https://github.com/raphael2025/personal-ai-brain/issues/23); technology review: [evaluation report](../research/technology-evaluation-2026-11.md)

Build labelled synthetic query corpus, lexical BM25 baseline, root/type/time filters, optional vector channel, hybrid rank fusion, evidence spans/citations, ranking regression tests.

Acceptance: report Recall@5/10, MRR, nDCG@10, citation precision, P50/P95 latency with dataset/hardware/versions/config. Compare every ranker against lexical baseline; no unmeasured quality claims.

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
