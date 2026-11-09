# ADR-0004: Evaluate lexical retrieval before vector or graph adoption

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Vector databases, graph retrieval, rerankers, and agent-memory frameworks add operational dependencies and may improve some question types while degrading others. Vendor benchmarks are not comparable unless corpus, labels, models, configuration, hardware, and metrics match.

PAB needs a retrieval foundation that is local-first, explainable, testable, and replaceable.

## Decision

1. Build and measure a PAB-native lexical/BM25 baseline before selecting a vector or graph backend.
2. Create a versioned synthetic corpus with labelled evidence spans and query classes: exact lookup, paraphrase, temporal, multi-hop, conflict, no-answer, and permission-denied.
3. Measure Recall@5/10, MRR, nDCG@10, citation precision/coverage, P50/P95 latency, ingestion throughput, resource use, and recovery behavior.
4. Add vector retrieval only when a version-pinned experiment demonstrates measurable improvement over the lexical baseline without unacceptable privacy, latency, or operational cost.
5. Add graph retrieval only when multi-hop evaluation demonstrates an incremental benefit that justifies graph extraction, storage, and maintenance.
6. Keep candidate backends behind replaceable adapters; no provider-specific schema becomes the canonical PAB knowledge model.
7. Publish benchmark scripts, raw result artifacts, versions, configuration, hardware, and random seeds. Do not present vendor headline scores as PAB results.

## Consequences

- BM25 and labelled evaluation are P1 priorities.
- Vector and graph infrastructure are optional and evidence-gated.
- Retrieval quality claims must be reproducible.
- A simpler local stack is preferred until measured workloads justify additional services.
