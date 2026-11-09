# Architecture Overview

**Status:** proposed; subject to ADR review and implementation evidence.

## 1. System boundary

Personal AI Brain is a local-first control plane for registering digital assets, deriving searchable representations, managing memory, and serving explicitly authorized context to AI clients.

Original files remain in their existing storage locations. The system stores references, metadata, extracted representations, and derived indexes. It must not silently move, rename, rewrite, or delete source files.

## 2. Logical components

| Component | Responsibility | Initial boundary |
|---|---|---|
| Asset Registry | Sources, stable asset IDs, locations, versions, metadata | Core domain |
| Discovery | Scan roots, detect additions/changes/removals/unavailable mounts | Worker |
| Ingestion | Parse formats and extract text/metadata | Worker adapters |
| Retrieval | Lexical, vector, metadata, temporal ranking | Core service |
| Memory Manager | Memory records, lifecycle, activation, conflict state | Core domain |
| Context Manager | Query plan, permissions, progressive loading, token budget | Core service |
| Provenance | Source spans, transformation lineage, model/parser versions | Cross-cutting |
| Policy & Audit | Access decisions, external egress controls, audit trail | Cross-cutting |
| Connectors | Filesystems, NAS, MCP, model gateways, AI clients | Adapters |

The first implementation should be a modular monolith with independently runnable workers. Split services only when operational evidence justifies it.

## 3. Progressive knowledge model

Content depth and activation temperature are separate dimensions.

### Content depth

- **L0 — identity and compact description:** enough to decide whether an asset or memory is relevant.
- **L1 — structured overview:** sections, entities, key facts, and navigable summaries.
- **L2 — detailed evidence:** extracted text, source spans, or the original file opened on demand.

These levels are not three mandatory copies of every file. They are derived views created only where useful.

### Activation temperature

- **Hot:** frequently or recently needed; eligible for fast retrieval and short-lived context caching.
- **Warm:** useful but not continuously loaded.
- **Cold:** retained and searchable at low cost; deeper content is activated on demand.

Cold knowledge is not deleted. Activation changes retrieval priority, not the existence or authority of source records.

## 4. Data authority and provenance

- Original source files are authoritative for their contents.
- Extracted text and summaries are derived artifacts.
- Embeddings are disposable indexes, not facts.
- Each derived artifact records source asset/version, extractor name/version, model identifier where applicable, creation time, and status.
- Every user-facing factual memory should be traceable to one or more source records.
- Conflicting claims remain distinguishable; do not silently overwrite history.

## 5. Node topology

The target deployment has a low-power always-on control node and optional compute workers.

- **Control node:** API, database, asset registry, scheduling, policy, audit, and lightweight retrieval.
- **Worker nodes:** parsing, OCR, transcription, embeddings, and local model inference.
- **Storage nodes:** NAS and removable media remain sources; availability is tracked separately from identity.

Workers should pull jobs, use leases/checkpoints, and safely resume after network interruption. A worker outage must not corrupt registry state.

## 6. Security model

- Default to local-only processing and deny external model egress.
- Use explicit per-connector and per-data-class permissions.
- Treat tool output and retrieved documents as untrusted data, not instructions.
- Keep secrets out of the repository and logs.
- Require authentication for all non-loopback APIs before network exposure.
- Restrict parser services to private networks; never expose unauthenticated parsing endpoints publicly.
- Log access decisions without copying sensitive document contents into logs.

## 7. Initial technology evaluation

Candidate technologies are experiments, not architectural dependencies until tested:

- OpenViking: progressive context and memory retrieval experiment.
- MemOS: long-term memory experiment.
- Cognee: entity and relationship extraction experiment.
- PostgreSQL plus lexical search and a vector extension/store: conventional baseline.

Selection criteria: retrieval quality, source traceability, incremental update correctness, data portability, operational complexity, local deployment, license compatibility, and recovery behavior.

## 8. Non-functional acceptance criteria

The initial benchmark should measure:
- Recall@5/10 and MRR on a labelled question set;
- P50/P95 retrieval latency;
- evidence/source attribution accuracy;
- false memory rate and conflict handling;
- incremental indexing latency and update consistency;
- worker restart and disconnected-storage recovery;
- external egress behavior and access-control correctness.

Targets must be reported with hardware, dataset size, configuration, and test method. Do not publish unqualified performance claims.
