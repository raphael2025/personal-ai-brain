# Roadmap

This roadmap is a planning document, not a claim that these capabilities already exist. Milestones move to **Done** only after code, tests, and acceptance evidence are merged.

## Phase 0 — Foundations

- [ ] Repository governance, architecture boundaries, and threat model
- [ ] Asset identity and storage-location data model
- [ ] Incremental discovery with safe handling of unavailable volumes
- [ ] Processing-job model with idempotency, retries, and checkpoints
- [ ] Baseline evaluation corpus and query set
- [ ] Compare OpenViking, MemOS, Cognee, and a conventional hybrid-RAG baseline
- [ ] Local development environment and CI

## Phase 1 — Asset Registry

- [ ] Register files and storage roots without modifying originals
- [ ] Stable identity using path-independent fingerprints where feasible
- [ ] Track file versions, locations, and availability
- [ ] Incremental scan and reconciliation
- [ ] Permission and exclusion rules

## Phase 2 — Ingestion and Retrieval

- [ ] Text and metadata extraction
- [ ] Document and code parsing
- [ ] OCR and media metadata
- [ ] Lexical + semantic retrieval baseline
- [ ] Evidence spans and source citations
- [ ] Retrieval evaluation and regression tests

## Phase 3 — Memory and Context

- [ ] L0/L1/L2 progressive content model
- [ ] Memory lifecycle and activation policy
- [ ] Context planning and token budgeting
- [ ] Conflict detection, freshness, and provenance
- [ ] Read-only API and MCP interface

## Phase 4 — Multi-node and integrations

- [ ] Pull-based worker execution and recovery
- [ ] Local model gateway
- [ ] Optional external model gateway with explicit policy
- [ ] AI client connectors
- [ ] Backup, restore, monitoring, and security review

## Release gates

A phase is not considered complete until:
- acceptance criteria are documented;
- tests run in CI;
- failure and recovery paths are exercised;
- security and privacy implications are reviewed;
- setup and migration instructions are reproducible.
