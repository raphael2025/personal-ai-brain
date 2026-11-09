# Technology Evaluation: OpenViking, MemOS, Cognee, and a PAB-native baseline

**Evaluation date:** 2026-11-10  
**Status:** desk research and architecture recommendation, not a benchmark or production selection.  
**Decision:** keep PAB's Asset Registry and source-of-truth model native; establish a lexical baseline first; evaluate external memory/graph/context engines only behind replaceable adapters.

## 1. Executive decision

Do not select one of these projects as the entire Personal AI Brain foundation. They solve overlapping but different problems:

- **OpenViking** is closest to a context database: unified resource/memory/skill representation, hierarchical context, L0/L1/L2 progressive loading, semantic retrieval, and asynchronous context processing. Its repository is AGPL-3.0, which creates material integration/distribution obligations. Treat it as a separately deployed experimental adapter, not a vendored core dependency.
- **MemOS (MemTensor/MemOS)** is a memory operating system with memory cubes, graph-shaped memory, multi-modal memory, asynchronous scheduling, and a self-hosted service. The main self-host deployment documented in its README uses Neo4j and Qdrant. Its separate local plugin uses SQLite and targets OpenClaw/Hermes. The repository is Apache-2.0. Evaluate the local plugin and service as distinct deployment choices; do not assume the whole server is a single-file SQLite product.
- **Cognee** is a knowledge pipeline that converts documents, code, and conversations into graph/vector/relational representations and exposes remember/recall/improve/forget operations. Its repository is Apache-2.0. It is a useful optional knowledge-graph/semantic extraction candidate, but its Postgres graph-store path is described upstream as a demo feature, with production graph capability licensed separately.
- **PAB-native hybrid baseline** is the recommended first implementation: PAB-owned asset identity/version/provenance and policy; PostgreSQL metadata/transactions; BM25 lexical retrieval; optional pgvector after benchmark evidence; graph relationships only when an evaluated use case justifies them.

No candidate should be chosen on star count or vendor benchmark numbers. The projects' benchmarks use different datasets, task definitions, model settings, and evaluation procedures.

## 2. Candidate comparison

| Dimension | OpenViking | MemOS (MemTensor) | Cognee | PAB-native baseline |
|---|---|---|---|---|
| Primary abstraction | Context database / virtual filesystem | Memory OS / memory cubes | Knowledge pipeline / graph memory | Digital-asset registry + evidence-backed knowledge |
| Strongest fit | Resource hierarchy, progressive context loading, agent context retrieval | Durable user/agent memory, trust, feedback, cross-agent reuse | Entity/relationship extraction, graph and vector retrieval | Asset identity, source lineage, permissions, reproducible retrieval |
| Data model | Viking URI tree; resources, memories, skills; L0/L1/L2 | Memory cubes; structured memory and multi-modal records | Documents/chunks/entities/relationships across relational, vector, graph stores | Asset, version, location, scan, artifact, claim, memory, evidence |
| Retrieval | Hierarchical semantic retrieval and reranking | Unified memory API; self-host service and local plugin differ | Graph/vector/keyword/hybrid strategies | BM25 first; vector/graph channels are optional |
| Ingestion | Parse/tree-build, async semantic processing | Async memory scheduling; local plugin has its own ingestion | add → cognify → search pipeline | Durable jobs and isolated extractors, still to be implemented |
| Local deployment | Self-host HTTP service; content/index storage layers | Main service uses Neo4j + Qdrant; local plugin uses SQLite | Local Python pipeline; backend composition depends on configuration | Local PostgreSQL control plane + source files in place |
| License | AGPL-3.0 | Apache-2.0 | Apache-2.0 | Apache-2.0 |
| Main caution | AGPL obligations; imported/context storage must not replace PAB source authority | Main service is a heavier graph/vector stack; distinguish it from SQLite plugin | Graph/Postgres feature maturity and model/provider configuration need verification | More engineering work; must build ingestion, retrieval and evaluation ourselves |

## 3. Detailed findings

### 3.1 OpenViking

Upstream describes OpenViking as a context database that unifies agent memory, resources, and skills in a directory-like structure. Its documented architecture separates client, service, retrieval, session, parsing, memory, and storage layers. It uses a content store plus vector index, asynchronous semantic processing, intent analysis, hierarchical retrieval, and optional reranking.

The L0/L1/L2 progressive context model aligns strongly with PAB's progressive disclosure goal:
- L0: low-cost abstract/metadata for relevance screening.
- L1: overview and navigable context.
- L2: detailed content/evidence on demand.

**PAB assessment**
- Reuse the conceptual model and test its retrieval behavior.
- Do not allow its virtual filesystem to become PAB's canonical asset registry.
- Do not silently copy or relocate original files into a second authoritative store.
- Keep PAB asset IDs, source versions, permissions, and evidence IDs authoritative.
- Because the repository declares AGPL-3.0, prefer a process/API boundary for any experiment and obtain license review before distributing a combined product or modified integration.

**Candidate experiment:** import a synthetic PAB fixture corpus into a separate OpenViking instance; compare hierarchical retrieval against BM25 and vector-only retrieval; verify deletion/export behavior and exact source citation mapping.

### 3.2 MemOS (MemTensor/MemOS)

The current MemTensor repository describes MemOS 2.0 as a memory operating system with a unified memory API, graph-structured and inspectable memory, multi-modal memory, memory cubes, asynchronous scheduling, and feedback/correction. The README distinguishes:
- Cloud API: hosted service.
- Self-host service: documented Docker deployment with Neo4j and Qdrant.
- Local plugin: separate OpenClaw/Hermes plugin using local SQLite, FTS5 + vector retrieval, deduplication, and skill evolution.

The repository declares Apache-2.0.

**PAB assessment**
- Memory cubes offer a useful isolation/sharing model for users, agents, projects, and sessions.
- Feedback/correction and graph-structured memories are relevant to the PAB Memory Manager.
- The local plugin is the lower-operational-cost candidate for a narrow agent-memory experiment.
- The full self-host service adds Neo4j/Qdrant and should not be treated as equivalent to the SQLite local plugin.
- PAB must retain its own provenance and confirmation semantics; an external memory engine cannot decide that inferred content is a user-confirmed fact.

**Candidate experiment:** evaluate local plugin data export/import, source attribution, conflict handling, memory deletion, namespace isolation, and multi-agent sharing on synthetic memory fixtures. Separately estimate the resource and operational cost of the Neo4j/Qdrant self-host stack.

### 3.3 Cognee

Cognee describes a pipeline that transforms documents, code, and conversations into connected memory. Its public API concepts include remember, recall, improve, and forget. Its documented flow extracts entities and relationships, creates searchable chunks, and retrieves graph/vector/code context. It supports local workflows and optional model providers; its repository declares Apache-2.0.

The current README states that the Postgres graph-store route is a demo feature and that production-ready graph functionality is available as a licensed product. This is an important deployment limitation: do not assume the whole production graph stack is freely available on PostgreSQL.

**PAB assessment**
- Strong candidate for optional entity/relationship extraction and knowledge graph experiments.
- Useful for testing whether graph context improves multi-hop questions over PAB's lexical/vector baseline.
- Avoid making Cognee's internal graph schema the PAB canonical domain model.
- Keep extracted claims linked to PAB asset-version evidence and processor manifests.
- Verify backend/license terms and local model requirements at the exact version selected.

**Candidate experiment:** run Cognee against a synthetic corpus with known entity relations; compare graph retrieval to BM25 and vector-only on multi-hop questions; record extraction errors, source-span coverage, runtime, memory, and dependency footprint.

### 3.4 PAB-native hybrid baseline

PAB has already established its PostgreSQL Asset Registry schema. The next step is a service layer and a reproducible lexical retrieval baseline, not immediate adoption of a graph database or a large vector stack.

Recommended first stack:
- PostgreSQL for roots, assets, versions, locations, scans, provenance metadata, jobs, and audit.
- Original files remain in user-controlled filesystems/NAS/removable media.
- Extracted text and chunks are versioned derived artifacts.
- BM25/lexical search first, with root/type/time filters and exact evidence spans.
- Add pgvector only after a labelled corpus shows measurable benefit.
- Add graph storage only if multi-hop evaluation shows improvement that justifies its operational cost.
- Keep memory as a separate domain from source assets and extracted knowledge.

This approach is slower to build initially but avoids coupling PAB's identity, deletion, permissions, and source-of-truth rules to any one retrieval engine.

## 4. Recommended architecture decision

1. **Adopt no candidate as a mandatory runtime dependency in v1.**
2. **PAB owns identity and provenance.** External systems receive stable PAB IDs and source/version references; they cannot mint authoritative asset identity.
3. **Implement BM25 first.** Build the labelled evaluation corpus and baseline before vector/graph selection.
4. **Use adapters for experiments.** OpenViking, MemOS, and Cognee must be optional adapters with export/import tests and clear data boundaries.
5. **Treat memory and evidence separately.** A memory can summarize evidence but cannot replace it. Inferred memory requires review/confirmation before being promoted to a user fact.
6. **Gate egress and licensing.** No personal content leaves the local environment unless a scoped user-approved policy permits it. AGPL integration needs explicit license review.
7. **Measure operations, not only recall.** Include cold-start, ingestion throughput, incremental update, deletion, crash recovery, CPU/RAM/disk, export/restore, and query latency.

## 5. Reproducible evaluation plan

Use one synthetic corpus and one labelled query set across all candidates. Keep real personal archives out of CI and research experiments.

### Corpus
- 1,000–10,000 synthetic documents across Markdown, PDF, HTML, code, and structured notes.
- Explicit source IDs, version IDs, timestamps, access scopes, and expected evidence spans.
- Queries grouped into exact lookup, paraphrase, temporal, multi-hop, conflict, no-answer, and permission-denied cases.

### Metrics
- Retrieval: Recall@5/10, MRR, nDCG@10, citation precision/coverage.
- Ingestion: docs/min, incremental reprocess count, failed-job recovery, duplicate handling.
- Operations: P50/P95 query latency, cold-start time, peak RSS, disk growth, backup/restore duration.
- Safety: unauthorized recall count (must be zero), deleted-source resurrection (must be zero), provenance loss (must be zero), egress without grant (must be zero).

### Fairness controls
- Pin commit/tag, model, embedding model, reranker, configuration, and random seed.
- Record CPU/RAM/storage and OS.
- Separate ingestion-time model calls from query-time model calls.
- Compare the same corpus, query labels, top-k, and evidence rules.
- Publish raw result JSON and benchmark scripts; do not compare vendor headline scores directly.

## 6. Current recommendation

**Build PAB-native registry + BM25 + evidence first.** Evaluate MemOS local plugin for the agent-memory edge, Cognee for optional graph extraction, and OpenViking only in an isolated experiment pending AGPL review. Do not add Neo4j, Qdrant, a graph database, or a model gateway to the core deployment until a reproducible benchmark demonstrates a clear gain.

## 7. Sources checked on 2026-11-10

- OpenViking repository and license: https://github.com/volcengine/OpenViking
- OpenViking architecture: https://docs.openviking.ai/en/concepts/01-architecture
- OpenViking documentation index: https://docs.openviking.ai/
- MemOS (MemTensor) repository and license: https://github.com/MemTensor/MemOS
- Cognee repository and license: https://github.com/topoteretes/cognee
- Cognee README and deployment notes: https://github.com/topoteretes/cognee/blob/main/README.md

Upstream documentation changes frequently. Re-check the exact commit, license, backend support, and deployment instructions before adding any dependency.
