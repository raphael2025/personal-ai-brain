# Project Status

**Current phase:** Phase 1 — Asset Registry foundation  
**Release status:** pre-alpha; not suitable for production use or ingestion of sensitive personal archives.

This page distinguishes merged and validated capabilities from planned architecture. A roadmap checkbox is not evidence that a capability works.

## Implemented and validated

| Capability | Current state | Limitations |
|---|---|---|
| SHA-256 file identity | Implemented | Path-based helper remains for standalone use; registry scans use descriptor-relative hashing |
| Directory discovery | Implemented | Read-only, no symlink traversal; fails closed without required POSIX primitives; not a hardened sandbox against hostile concurrent filesystem changes |
| Descriptor-relative file hashing and bounded source reads | Implemented | Root-relative opens, O_NOFOLLOW, O_NONBLOCK, size/mtime checks, and before/after descriptor checks; caller-side root authorization/mount mapping and cross-platform validation remain open |
| StorageRoot / AssetLocation models | Implemented | URI/path validation and explicit collision-safe path-normalizer migration are implemented for v1-exact/v1-casefold; cross-platform semantics still need broader validation |
| PostgreSQL Asset Registry schema | Implemented | Manual migration; no migration runner or rollback automation yet |
| Asset identity and content versions | Implemented | Stable logical asset IDs; fingerprints do not auto-merge different paths |
| Storage locations and scan history | Implemented | Current location and historical events are stored |
| COMPLETE-only reconciliation | Implemented | PARTIAL/FAILED scans never infer missing locations; complete empty scans can mark locations missing |
| Registry repository and scan service | Implemented | Initial root/scan path; scan completion no longer implicitly marks unseen locations missing; operator reconciliation is explicit and audited |
| CLI | Initial implementation | Registry commands plus worker register/grant-root/revoke-root/run and extract enqueue; foreground worker only, no Windows service/daemon or remote worker |
| Scan replay handling | Implemented | Identical finalization is idempotent; conflicting replay is rejected |
| CI | Implemented | Python 3.11–3.13; PR #34 passed all matrix jobs |
| CodeQL | Implemented | PR #34 passed; automated analysis is not a complete security audit |
| Secret scanning | Implemented | PR #34 passed Gitleaks |
| Durable job/attempt/lease foundation | Implemented | PostgreSQL schema/functions, Python repository/runtime, worker registration, root grants, extraction enqueue, foreground run, heartbeat and signal drain; process supervision and crash-recovery drills remain |
| Lease-fenced artifact publication | Initial implementation | PostgreSQL JSONB payload publication verifies active lease owner/generation/expiry, job config digest, and immutable source SHA; wired to the text extraction handler; no external blob staging or garbage collection yet |
| Root-scoped worker source authorization | Initial implementation | Revocable worker/root grants, audited CLI grant/revoke, local TOML mount mapping, active job-lease verification, descriptor-relative bounded reads, and immutable SHA-256 verification |
| Text/Markdown extraction pipeline | Initial implementation | End-to-end enqueue, active-lease source read, UTF-8 extraction, fenced PostgreSQL JSONB artifact publication, and job completion; 16 MiB bound; other document formats are not implemented |
| BM25 lexical retrieval and synthetic benchmark | Initial implementation | Dependency-free in-memory BM25, metadata filters, deterministic ranking, five labelled queries over four synthetic documents; not a persistent or production search service |
| Contributor architecture and research docs | Implemented | Blueprint is a target design; not every target module exists |

## Not implemented yet

- OS-level worker sandboxing, per-worker database credentials, Windows service/daemon supervision, remote worker protocol, external content-addressed artifact storage/staging/garbage collection, and crash/recovery drills
- Durable scan resume, interrupted RUNNING scan recovery, and crash recovery
- Rename/move candidate workflow and duplicate-asset review UI
- PDF/DOCX/HTML/archive/image/audio/video extractors and corresponding end-to-end artifact pipelines; current end-to-end path supports bounded UTF-8 text/Markdown/code
- OCR, transcription, embeddings, persistent/chunk-level retrieval, vector retrieval, and a larger labelled evaluation corpus
- Memory lifecycle, activation scoring, and progressive L0/L1/L2 runtime
- Knowledge graph, claim/evidence model, and conflict resolution
- Context planner, token budgeting, ContextBundle API, and MCP
- Authentication, authorization, encryption, backup/restore, and external egress enforcement
- Multi-node workers and desktop/local web UI

## Current CLI

Install the optional PostgreSQL support and developer tools:

    python -m pip install -e ".[postgres,dev]"

Set PAB_DATABASE_URL. Apply migrations 0001–0004 in order to enable the complete worker path; the registry-only path starts at migration 0001. Then use:

    pab root add --name "Documents" --uri "file:///home/user/Documents" --kind local --case-sensitive yes
    pab root list
    pab scan <root-uuid>
    pab scan-status --root-id <root-uuid>
    pab asset list --root-id <root-uuid>
    pab asset inspect <asset-uuid>
    pab reconcile preview <scan-uuid>
    pab reconcile apply <scan-uuid> --actor operator-name

SMB/NFS roots require an explicit local mount path with pab scan <root-uuid> --path /mnt/share. See [Registry Service and CLI](docs/development/registry-service.md) for details and limitations.

Worker commands:

    pab worker register --worker-id <worker-uuid> --name "text worker" --capability text
    pab worker grant-root --worker-id <worker-uuid> --root-id <root-uuid> --actor operator
    pab extract enqueue --asset-version-id <version-uuid> --root-id <root-uuid>
    pab worker run --worker-id <worker-uuid> --mounts-config /etc/pab/worker-mounts.toml --once

See [Local Worker Operations](docs/development/worker-operations.md) for mount configuration, continuous operation, revocation, and limits.

Run the synthetic lexical retrieval benchmark (no database required):

    python -m personal_ai_brain.evaluation.benchmark evaluation/datasets/synthetic-v1 --output benchmark-results/bm25-synthetic-v1.json

See [BM25 Baseline](docs/research/bm25-baseline.md).

## Security warning

Do not point the scanner at hostile or attacker-writable filesystems and assume it is a complete security boundary. It is read-only, but hostile concurrent filesystem changes and platform-specific behavior still require further validation. Do not expose any future API or parser service to a network until authentication, authorization, isolation, and resource limits are implemented and tested. External model egress is a design requirement, not yet an enforced runtime control.

## Validation policy

- CI must pass on the current commit before a change is considered validated.
- CodeQL success does not equal a complete security review.
- Performance targets require reproducible benchmarks with hardware, dataset, versions, and configuration recorded.
- Integrations remain experimental until their versions, licenses, update behavior, recovery behavior, and provenance have been tested.


See [Durable Jobs and Worker Lease Foundation](docs/development/durable-jobs.md), [Lease-Fenced Artifact Publication](docs/development/artifact-publication.md), and [Local Worker Operations](docs/development/worker-operations.md) for the migration, CLI, and security contracts.
