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
- [ ] Synthetic evaluation corpus and baseline query set
- [x] Desk research comparison: OpenViking, MemOS, Cognee, and hybrid retrieval baseline (benchmark still pending in Issue #5)

## Phase 1 — Asset Registry and durable processing (P0)
- [x] Root enrollment and initial storage-root policy
- [x] Persistent assets, versions, locations, scan runs, observations
- [x] Transactional COMPLETE-only reconciliation
- [ ] Rename/duplicate candidate resolution without destructive auto-merge
- [x] Durable job schema, Python repository adapter, and pull-based worker runtime (PRs #38–#39)
- [ ] Worker CLI, process supervision, authenticated source access, and fenced artifact publication
- [x] Registry CLI: scan status, asset list/inspect, dry-run and explicit audited reconciliation
- [ ] Worker runtime/CLI, artifact staging and atomic publication
- [x] Explicit collision-safe path-normalizer migration with dry-run, collision refusal, audit, and transaction rollback (PR #40)

## Phase 2 — Extraction, provenance, and search (P1)
- [x] Initial bounded UTF-8 text/Markdown/code extractor (PR #41)
- [ ] Root-scoped source reader and PDF/DOCX/HTML/archive extractors
- [ ] Versioned artifacts and rebuild manifests
- [ ] Sandboxed extraction with resource limits
- [ ] Lexical BM25 retrieval baseline
- [ ] Labelled evaluation and retrieval regression tests
- [ ] Optional vector channel and measured hybrid ranking
- [ ] Evidence spans and citations

## Phase 3 — Knowledge, memory, and context (P2)
- [ ] L0/L1/L2 progressive content model
- [ ] Explicit memory origins and lifecycle
- [ ] Entity/claim/evidence graph and conflict handling
- [ ] Freshness and activation policy (separate from content depth)
- [ ] Principal/scope/classification model
- [ ] Deny-by-default policy engine and append-only audit
- [ ] ContextBundle assembly, token budget, citations, omissions
- [ ] External model egress grants and revocation

## Phase 4 — API, clients, and operations (P3)
- [ ] Versioned local HTTP API and OpenAPI contract
- [ ] Local UI
- [ ] Read-only MCP adapter, then explicitly confirmed mutating tools
- [ ] Pull-based multi-node workers and recovery
- [ ] Backup/restore, metrics, health, redacted logs
- [ ] Security review and reproducible deployment guide

## Release gates

A phase is not complete until acceptance criteria are documented, CI passes, failure/recovery paths are exercised, security/privacy implications are reviewed, migrations are reproducible, and project status is updated. Performance and retrieval-quality claims require benchmark evidence with hardware, dataset, versions, and configuration.
