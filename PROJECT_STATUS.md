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
| CLI | Initial implementation | pab root add/list, scan, scan-status, asset list/inspect, reconcile preview/apply; worker commands and scan resume remain |
| Scan replay handling | Implemented | Identical finalization is idempotent; conflicting replay is rejected |
| CI | Implemented | Python 3.11–3.13; PR #34 passed all matrix jobs |
| CodeQL | Implemented | PR #34 passed; automated analysis is not a complete security audit |
| Secret scanning | Implemented | PR #34 passed Gitleaks |
| Durable job/attempt/lease foundation | Implemented | PostgreSQL schema/functions and Python PostgresJobRepository + pull-based WorkerRuntime; no worker CLI, authenticated source access, or artifact publication yet |
| Text/Markdown extraction adapter | Initial implementation | UTF-8, 16 MiB bound, source SHA-256 verification, explicit malformed-input outcomes; not yet wired to source reader, artifact store, or WorkerRuntime |
| Contributor architecture and research docs | Implemented | Blueprint is a target design; not every target module exists |

## Not implemented yet

- Worker CLI/process supervisor, graceful signal/drain controls, authenticated root-scoped source access, artifact staging/publication, and operational recovery
- Durable scan resume, interrupted RUNNING scan recovery, and crash recovery
- Rename/move candidate workflow and duplicate-asset review UI
- PDF/DOCX/HTML/archive/image/audio/video extractors, authorized worker source mapping, and end-to-end artifact pipeline
- OCR, transcription, embeddings, BM25, vector retrieval, and evaluation corpus
- Memory lifecycle, activation scoring, and progressive L0/L1/L2 runtime
- Knowledge graph, claim/evidence model, and conflict resolution
- Context planner, token budgeting, ContextBundle API, and MCP
- Authentication, authorization, encryption, backup/restore, and external egress enforcement
- Multi-node workers and desktop/local web UI

## Current CLI

Install the optional PostgreSQL support and developer tools:

    python -m pip install -e ".[postgres,dev]"

Set PAB_DATABASE_URL, apply the SQL migration manually, then use:

    pab root add --name "Documents" --uri "file:///home/user/Documents" --kind local --case-sensitive yes
    pab root list
    pab scan <root-uuid>
    pab scan-status --root-id <root-uuid>
    pab asset list --root-id <root-uuid>
    pab asset inspect <asset-uuid>
    pab reconcile preview <scan-uuid>
    pab reconcile apply <scan-uuid> --actor operator-name

SMB/NFS roots require an explicit local mount path with pab scan <root-uuid> --path /mnt/share. See [Registry Service and CLI](docs/development/registry-service.md) for details and limitations.

## Security warning

Do not point the scanner at hostile or attacker-writable filesystems and assume it is a complete security boundary. It is read-only, but hostile concurrent filesystem changes and platform-specific behavior still require further validation. Do not expose any future API or parser service to a network until authentication, authorization, isolation, and resource limits are implemented and tested. External model egress is a design requirement, not yet an enforced runtime control.

## Validation policy

- CI must pass on the current commit before a change is considered validated.
- CodeQL success does not equal a complete security review.
- Performance targets require reproducible benchmarks with hardware, dataset, versions, and configuration recorded.
- Integrations remain experimental until their versions, licenses, update behavior, recovery behavior, and provenance have been tested.


See [Durable Jobs and Worker Lease Foundation](docs/development/durable-jobs.md) for the migration, SQL function contract, and current limitations.


The [Durable Jobs and Worker Lease guide](docs/development/durable-jobs.md) now includes the Python repository adapter and pull-based runtime. The worker still cannot publish artifacts or read arbitrary source paths through a privileged interface.
