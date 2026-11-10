# Implementation Map and Contributor Work Packages

This is the execution map for turning the architecture into a working product. Implement each work package as focused PRs with tests. Dependencies are deliberate; do not build UI on unstable contracts.

## A — Asset Registry (P0) — [Issue #35](https://github.com/raphael2025/personal-ai-brain/issues/35)

Goal: know which assets exist, where they are, and which versions were observed.

Merged: PostgreSQL schema; root enrollment; file identity/version/location persistence; scan observations; COMPLETE-only reconciliation; descriptor-relative hashing; root/scan/scan-history/asset-inspection CLI; explicit reconciliation preview/apply; collision-safe path-normalizer migration. Remaining: interrupted RUNNING scan recovery, operator recovery, rename/duplicate candidate workflow, cross-platform hostile-filesystem validation, and a 100k-entry scan benchmark.

Acceptance: identical finalization replay is idempotent and conflicting replay is rejected; partial/failed scans never mark missing; identical bytes at different paths remain separate pending resolution; sources never modified.

## B — Durable Jobs and Workers (P0) — [Issue #21](https://github.com/raphael2025/personal-ai-brain/issues/21)

Delivered in PRs #38–#39: job/attempt/lease schema, fencing and heartbeat, worker registration/capability matching, retry/backoff/cancellation, and pull-based runtime. PR #44 adds PostgreSQL JSONB artifact publication fenced by the active lease and idempotent by source/processor/config identity. PR #45 adds revocable worker/root read grants, audited grant/revoke, worker-local TOML mount mapping, active job-lease verification during source resolution, bounded descriptor-relative no-follow reads, and immutable SHA-256 verification. PR #46 adds worker registration/grant/revoke/run CLI, extraction enqueue, a built-in text handler, foreground signal drain, and an end-to-end PostgreSQL pipeline test.

Remaining: OS sandboxing, per-worker DB credentials, service supervision, external content-addressed staging/blob publication, orphan cleanup, concurrent-worker stress tests, and crash/recovery drills.

Acceptance: kill worker mid-job and prove lease recovery; stale lease cannot publish an artifact; duplicate enqueue/publication is idempotent; retry budget deterministic. Database publication fencing is covered; external blob publication and process-level recovery remain unverified.

## C — Extraction and Provenance (P1) — [Issue #22](https://github.com/raphael2025/personal-ai-brain/issues/22)

PR #46 wires the bounded text/Markdown/code extractor end-to-end: durable job enqueue, root-granted active-lease source resolution, descriptor-relative read and SHA verification, extraction, fenced artifact publication, and job completion. PR #44 persists output and source provenance in PostgreSQL.

Remaining: external artifact store/rebuild manifests, PDF/DOCX/HTML/archive/image/audio/video adapters, OCR/transcription, and enforced CPU/memory/time/archive-expansion isolation. Keep unsupported formats explicit and preserve source-version provenance.

Acceptance: malformed/adversarial synthetic corpus; unsupported types explicitly reported; same source+extractor+config idempotent; source never modified.

## D — Search and Evaluation (P1) — [Issue #23](https://github.com/raphael2025/personal-ai-brain/issues/23); technology review: [evaluation report](../research/technology-evaluation-2026-11.md)

PR #43 established dependency-free BM25, Unicode tokenization, deterministic tie-breaking, root/type/time filters, and a reproducible synthetic benchmark. PR #47 adds a PostgreSQL adapter over ready extracted-text artifacts, current available locations, source-version/path/SHA evidence, bounded per-request in-memory indexing (5,000 documents / 64 MiB), and CLI filters.

Remaining: expand the four-document/five-question synthetic corpus; add exact evidence spans and chunk/version citations; build a persistent inverted index; compare optional vector/hybrid channels only against the lexical baseline.

Acceptance: report Recall@5/10, MRR, nDCG@10, citation precision, P50/P95 latency with dataset/hardware/versions/config. Current benchmark is a synthetic smoke test, not a representative personal archive benchmark.

## E — Knowledge and Memory (P2) — [Issue #24](https://github.com/raphael2025/personal-ai-brain/issues/24)

PR #48 adds the first executable memory foundation: origin/state/evidence models; PostgreSQL create/get/transition/confirm repository; source-version evidence links; model-inferred and source-derived candidates; explicit promotion to user_confirmed; append-only transition history.

Remaining: immutable memory revisions, update/deletion and derived-index invalidation, freshness/activation scoring, conflict resolution, entity/claim/evidence graph, L0/L1/L2 progressive loading, and integration with ContextBundle and policy enforcement. Actor strings are audit metadata, not authenticated principals.

Acceptance: model inference cannot become user-confirmed without an explicit confirmation call; conflicts remain separately addressable; every source-derived memory links to an exact asset version; deletion invalidates derived indexes/caches once those components exist.

## F — Context Manager and Policy (P2) — [Issue #25](https://github.com/raphael2025/personal-ai-brain/issues/25)

Deliver principals/scopes/classifications; deny-by-default authorization; resource-level checks before retrieval expansion; context budgeter/progressive expansion; citation map/omission reasons; append-only access audit; provider-specific egress approval/revocation.

Acceptance: denied resource never reaches client; policy outage fails closed; cache scoped by principal/policy version; egress disabled absent scoped grant; prompt-injection and provider-mismatch tests.

## G — API, MCP, and UI (P3)

Deliver versioned local HTTP API/OpenAPI; read-only MCP tools first; desktop/local web UI for status, approvals, evidence. Mutating tools require explicit authorization and confirmation.

Acceptance: API/MCP share application services and policy; no connector bypass; local-only bind default; factual results include evidence references.

## H — Multi-node Operations (P3) — [Issue #27](https://github.com/raphael2025/personal-ai-brain/issues/27)

Deliver outbound worker polling; capability-aware queues; encrypted transport and worker identity; backup/restore; offline recovery; metrics and redacted logs.

Acceptance: control-node reboot preserves registry/jobs; worker disconnect does not corrupt state; restore drill passes; no public worker listener.

## Priority for contributors

| Priority | Package | Good first PR |
|---|---|---|
| P0 | Registry recovery and rename candidates | interrupted scan cleanup + tests |
| P0 | Worker hardening | sandbox contract + recovery drill |
| P1 | Extractors | one isolated extractor |
| P1 | Evaluation corpus | synthetic docs + labelled queries |
| P1 | Persistent retrieval | inverted-index adapter + benchmark |
| P2 | Memory lifecycle | revisions + deletion invalidation |
| P2 | Policy engine | deny-by-default evaluator |
| P3 | MCP adapter | read-only tools over stable services |
| P3 | UI | only after API contracts stabilize |

## Definition of done

Each package needs an issue with scope/dependencies/acceptance; contract and failure tests; reversible migration or documented forward-only policy; passing CI; updated docs/status; synthetic fixtures only; security/privacy review.
