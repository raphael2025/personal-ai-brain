# Roadmap

This roadmap is a delivery sequence, not a claim that planned capabilities exist. A milestone moves to Done only after code, tests, security review, and acceptance evidence are merged.

The detailed execution plan is [Implementation Map](docs/development/implementation-map.md); the target system is [System Blueprint v1](docs/architecture/system-blueprint.md).

## Phase 0 — Architecture and foundations
- [x] Repository governance, CI, security scanning, contribution templates
- [x] Initial local-first architecture and threat-model direction
- [x] System Blueprint v1: domains, data flow, state machines, API, deployment, security invariants
- [x] Module contracts, data lifecycle, context/egress policy, implementation map
- [x] ADR review of the v1 system blueprint and canonical registry/retrieval boundaries
- [x] Registry domain, PostgreSQL persistence, and initial scan service validated end-to-end
- [ ] Cross-platform scanner guarantees and hostile-filesystem validation
- [x] Initial synthetic evaluation corpus and labelled baseline query set (four documents/five questions; expansion remains)
- [x] Desk research comparison: OpenViking, MemOS, Cognee, and hybrid retrieval baseline (reproducible comparative benchmark still pending in Issue #5)

## Phase 1 — Asset Registry and durable processing (P0)
- [x] Root enrollment and storage-root policy
- [x] Persistent assets, immutable versions, locations, scan runs, and observations
- [x] Transactional COMPLETE-only reconciliation with explicit preview/apply
- [ ] Rename/duplicate candidate resolution without destructive auto-merge
- [x] Durable job schema, repository, capability-aware claims, lease heartbeat/fencing, retry, and cancellation (PRs #38–#39)
- [x] Worker registration/grant/revoke/run CLI and extraction enqueue (PR #46)
- [x] Root-scoped worker source authorization and bounded descriptor-relative reads (PR #45)
- [x] Lease-fenced PostgreSQL artifact publication (PR #44)
- [x] Registry CLI: scan history, asset list/inspect, reconciliation dry-run/apply, and path-normalizer migration (PRs #37 and #40)
- [ ] Interrupted scan recovery, worker process supervision, OS sandboxing, per-worker DB credentials, and crash/recovery drills
- [ ] External content-addressed artifact staging, atomic blob publication, and orphan cleanup

## Phase 2 — Extraction, provenance, and search (P1)
- [x] Initial bounded UTF-8 text/Markdown/code extractor (PR #41)
- [x] Bounded descriptor-relative no-follow source reader (PR #42)
- [x] End-to-end text/Markdown/code extraction scheduling and publication (PR #46)
- [ ] PDF/DOCX/HTML/archive/image/audio/video extractors and their end-to-end pipelines
- [ ] Sandboxed extraction with CPU, memory, time, and archive-expansion limits
- [x] Versioned artifact provenance and lease-fenced PostgreSQL JSONB publication (PR #44)
- [x] Initial in-memory lexical BM25 baseline with deterministic ranking and metadata filters (PR #43)
- [x] Local PostgreSQL-backed search over persisted extracted-text artifacts, bounded to 5,000 documents / 64 MiB per request (PR #47)
- [x] CLI search with root, document-type, and modified-time filters (PR #47)
- [x] Reproducible synthetic benchmark reporting Recall@5/10, MRR, nDCG@10, citation precision, and latency (PR #43)
- [ ] Expand labelled evaluation corpus and integrate persistent chunk/version retrieval regression tests
- [ ] Persistent inverted index, exact evidence spans/citations, optional vector channel, and measured hybrid ranking

## Phase 3 — Knowledge, memory, and context (P2)
- [x] Initial memory origins/states, source-version evidence, explicit confirmation, and append-only transition history (PR #48)
- [ ] Memory revision history, deletion invalidation, freshness/activation scoring, and lifecycle service integration
- [ ] L0/L1/L2 progressive content model and context-depth/activation separation
- [ ] Entity/claim/evidence graph, conflict handling, and duplicate review
- [ ] Principal/scope/classification model and deny-by-default policy engine
- [ ] ContextBundle assembly, token budget, citations, omissions, and policy-version cache keys
- [ ] External model egress grants, provider matching, revocation, and audit

## Phase 4 — API, clients, and operations (P3)
- [ ] Versioned local HTTP API and OpenAPI contract
- [ ] Local UI
- [ ] Read-only MCP adapter, then explicitly confirmed mutating tools
- [ ] Pull-based multi-node workers and recovery
- [ ] Backup/restore, metrics, health, redacted logs
- [ ] Security review and reproducible deployment guide

## Release gates

A phase is not complete until acceptance criteria are documented, CI passes, failure/recovery paths are exercised, security/privacy implications are reviewed, migrations are reproducible, and project status is updated. Performance and retrieval-quality claims require benchmark evidence with hardware, dataset, versions, and configuration.
