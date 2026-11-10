# Project Status

**Current phase:** Phase 2 — extraction, provenance, and local search, with an initial memory foundation  
**Release status:** pre-alpha; not suitable for production use or ingestion of sensitive personal archives.

This page distinguishes merged and validated capabilities from planned architecture. A roadmap checkbox is not evidence that a capability works.

## Implemented and validated

| Capability | Current state | Limitations |
|---|---|---|
| SHA-256 file identity | Implemented | Path-based helper remains for standalone use; registry scans use descriptor-relative hashing |
| Directory discovery | Implemented | Read-only, no symlink traversal; fails closed without required POSIX primitives; not a hardened sandbox against hostile concurrent filesystem changes |
| Descriptor-relative file hashing and bounded source reads | Implemented | Root-relative opens, O_NOFOLLOW, O_NONBLOCK, size/mtime checks, and before/after descriptor checks; cross-platform guarantees and hostile concurrent rename validation remain open |
| StorageRoot / AssetLocation models | Implemented | URI/path validation and explicit collision-safe v1-exact/v1-casefold path-normalizer migration; broader platform-specific semantics remain |
| PostgreSQL Asset Registry | Implemented | Manual migrations; no migration runner or automated rollback tooling |
| Asset identity, immutable content versions, locations, and scan history | Implemented | Different paths are not automatically merged even when bytes match |
| COMPLETE-only reconciliation | Implemented | PARTIAL/FAILED scans never infer missing locations; operator preview/apply is explicit and audited |
| Registry CLI | Implemented | Root enrollment/listing, scan, scan history, asset list/inspect, reconciliation preview/apply, and normalizer migration; interrupted RUNNING scan recovery remains |
| Durable jobs and worker leases | Initial implementation | Idempotent enqueue, capability-aware claims, heartbeat, fencing, bounded retry/cancellation, and pull-based runtime; crash drills, process supervision, OS sandboxing, and per-worker DB credentials remain |
| Worker source authorization | Initial implementation | Revocable worker/root grants, audit events, local TOML mount mapping, active-lease checks, descriptor-relative bounded reads, and SHA-256 verification; actor identity is not yet backed by the full policy engine |
| Lease-fenced artifact publication | Initial implementation | PostgreSQL JSONB publication checks active lease, config digest, and immutable source SHA; external content-addressed blob staging and orphan cleanup remain |
| Text/Markdown/code extraction | Initial end-to-end path | Bounded UTF-8 extraction (16 MiB), durable enqueue, authorized source read, fenced artifact publication, and job completion; PDF/DOCX/HTML/archive/image/audio/video are not implemented |
| BM25 and local search | Initial implementation | PostgreSQL adapter searches ready extracted-text artifacts for current available locations; BM25 index is rebuilt per request, capped at 5,000 documents / 64 MiB; no persistent inverted index, exact evidence spans, or API authorization |
| Synthetic retrieval benchmark | Initial implementation | Reproducible smoke benchmark with four synthetic documents and five labelled questions; not representative of personal archives |
| Explicit memory lifecycle | Initial implementation | Origins/states, source-version evidence, explicit candidate confirmation, content hash, and append-only transition events; no revision/deletion workflow, activation scoring, conflict resolution, or authenticated confirmation |
| CI, CodeQL, and secret scanning | Implemented | Mainline PRs #47 and #48 passed Python 3.11–3.13 CI, CodeQL, and Gitleaks; automated checks are not a complete security audit |
| Architecture and research documentation | Implemented | Blueprint describes the target system; not every target module exists |

## Not implemented yet

- Durable scan resume, interrupted RUNNING scan recovery, and operator recovery for abandoned scans
- Rename/move candidate workflow and duplicate-asset review
- OS-level worker sandboxing, per-worker database credentials, Windows service/daemon supervision, remote worker protocol, crash/recovery drills
- External content-addressed artifact storage, staging, atomic blob publication, rebuild manifests, and orphan garbage collection
- PDF/DOCX/HTML/archive/image/audio/video extraction; OCR and transcription
- Persistent inverted index, chunk-level retrieval, exact evidence spans/citations, embeddings, vector retrieval, and a larger labelled evaluation corpus
- Memory revisions, deletion invalidation, freshness/activation scoring, conflict resolution, entity/claim/evidence graph, and progressive L0/L1/L2 runtime
- Principal/scope/classification model, deny-by-default policy engine, authenticated user confirmation, ContextBundle assembly, token budgeting, and external-model egress enforcement
- Versioned local API, MCP, desktop/local web UI
- Multi-node workers, backup/restore, metrics, and operational dashboards

## Current CLI

Install PostgreSQL support and developer tools:

    python -m pip install -e ".[postgres,dev]"

Set PAB_DATABASE_URL without putting the connection string in shell history. Apply migrations 0001–0005 in order:

    read -rsp "PAB_DATABASE_URL: " PAB_DATABASE_URL; echo; export PAB_DATABASE_URL
    for migration in infrastructure/postgres/migrations/000*.sql; do
        psql "$PAB_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
    done

Registry operations:

    pab root add --name "Documents" --uri "file:///home/user/Documents" --kind local --case-sensitive yes
    pab root list
    pab scan <root-uuid>
    pab scan-status --root-id <root-uuid>
    pab asset list --root-id <root-uuid>
    pab asset inspect <asset-uuid>
    pab reconcile preview <scan-uuid>
    pab reconcile apply <scan-uuid> --actor operator-name

SMB/NFS roots require an explicit local mount path with pab scan <root-uuid> --path /mnt/share. See [Registry Service and CLI](docs/development/registry-service.md).

Worker and extraction operations:

    pab worker register --worker-id <worker-uuid> --name "text worker" --capability text
    pab worker grant-root --worker-id <worker-uuid> --root-id <root-uuid> --actor operator
    pab extract enqueue --asset-version-id <version-uuid> --root-id <root-uuid>
    pab worker run --worker-id <worker-uuid> --mounts-config /etc/pab/worker-mounts.toml --once

See [Local Worker Operations](docs/development/worker-operations.md). The worker is a foreground local process, not a supervised service.

Local lexical search:

    pab search "project release owner" --limit 10
    pab search "project release owner" --root-id <root-uuid>
    pab search "project release owner" --document-type md

Search reads ready inline JSONB text artifacts and rebuilds a bounded in-memory BM25 index for each request. See [Persisted Lexical Search](docs/development/persisted-search.md).

Run the synthetic lexical retrieval benchmark without a database:

    python -m personal_ai_brain.evaluation.benchmark evaluation/datasets/synthetic-v1 --output benchmark-results/bm25-synthetic-v1.json

See [BM25 Baseline](docs/research/bm25-baseline.md).

## Memory lifecycle foundation

Migration 0005 adds explicit memory origins and states, exact source-version evidence, and append-only transition history. Model-inferred and source-derived memories start as candidates. Promotion to user-confirmed/active requires the explicit repository confirmation operation.

The actor value is currently audit metadata, not authentication. Do not expose memory confirmation or local search through an unauthenticated API/MCP endpoint. See [Explicit Memory Lifecycle v1](docs/development/memory-lifecycle.md).

## Security warning

Do not point the scanner at hostile or attacker-writable filesystems and assume it is a complete security boundary. Do not expose worker, search, parser, memory, or future API services to a network until authentication, authorization, isolation, and resource limits are implemented and tested. External model egress is a design requirement, not yet an enforced runtime control.

## Validation policy

- CI must pass on the current commit before a change is considered validated.
- CodeQL success does not equal a complete security review.
- Performance and retrieval-quality claims require reproducible benchmarks with hardware, dataset, versions, and configuration.
- Integrations remain experimental until versions, licenses, update behavior, recovery behavior, and provenance have been tested.

See [Durable Jobs and Worker Lease Foundation](docs/development/durable-jobs.md), [Lease-Fenced Artifact Publication](docs/development/artifact-publication.md), [Local Worker Operations](docs/development/worker-operations.md), [Persisted Lexical Search](docs/development/persisted-search.md), and [Explicit Memory Lifecycle](docs/development/memory-lifecycle.md).
