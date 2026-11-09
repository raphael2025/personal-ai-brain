# Project Status

**Current phase:** Phase 1 — Asset Registry foundation  
**Release status:** pre-alpha; not suitable for production use or ingestion of sensitive personal archives.

This page distinguishes merged and validated capabilities from planned architecture. A roadmap checkbox is not evidence that a capability works.

## Implemented and validated

| Capability | Current state | Limitations |
|---|---|---|
| SHA-256 file identity | Implemented | Path-based helper remains for standalone use; registry scans use descriptor-relative hashing |
| Directory discovery | Implemented | Read-only, no symlink traversal; fails closed without required POSIX primitives; not a hardened sandbox against hostile concurrent filesystem changes |
| Descriptor-relative file hashing | Implemented | Root-relative opens, O_NOFOLLOW, O_NONBLOCK, discovery metadata checks, and before/after descriptor checks; cross-platform validation remains open |
| StorageRoot / AssetLocation models | Implemented | URI/path validation exists; platform-specific normalizer migration is not implemented |
| PostgreSQL Asset Registry schema | Implemented | Manual migration; no migration runner or rollback automation yet |
| Asset identity and content versions | Implemented | Stable logical asset IDs; fingerprints do not auto-merge different paths |
| Storage locations and scan history | Implemented | Current location and historical events are stored |
| COMPLETE-only reconciliation | Implemented | PARTIAL/FAILED scans never infer missing locations; complete empty scans can mark locations missing |
| Registry repository and scan service | Implemented | Initial root/scan path; asset browsing, dry-run, scan resume, and crash recovery remain |
| CLI | Initial implementation | pab root add, pab root list, and pab scan; no asset/worker commands yet |
| Scan replay handling | Implemented | Identical finalization is idempotent; conflicting replay is rejected |
| CI | Implemented | Python 3.11–3.13; PR #34 passed all matrix jobs |
| CodeQL | Implemented | PR #34 passed; automated analysis is not a complete security audit |
| Secret scanning | Implemented | PR #34 passed Gitleaks |
| Contributor architecture and research docs | Implemented | Blueprint is a target design; not every target module exists |

## Not implemented yet

- Durable job/attempt/lease model, worker recovery, and stale-scan cleanup
- Explicit path-normalizer migration and dry-run reconciliation
- Asset list/inspect and scan status CLI commands
- Rename/move candidate workflow and duplicate-asset review UI
- Document, image, audio, video, archive, and code extraction pipelines
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

SMB/NFS roots require an explicit local mount path with pab scan <root-uuid> --path /mnt/share. See [Registry Service and CLI](docs/development/registry-service.md) for details and limitations.

## Security warning

Do not point the scanner at hostile or attacker-writable filesystems and assume it is a complete security boundary. It is read-only, but hostile concurrent filesystem changes and platform-specific behavior still require further validation. Do not expose any future API or parser service to a network until authentication, authorization, isolation, and resource limits are implemented and tested. External model egress is a design requirement, not yet an enforced runtime control.

## Validation policy

- CI must pass on the current commit before a change is considered validated.
- CodeQL success does not equal a complete security review.
- Performance targets require reproducible benchmarks with hardware, dataset, versions, and configuration recorded.
- Integrations remain experimental until their versions, licenses, update behavior, recovery behavior, and provenance have been tested.
