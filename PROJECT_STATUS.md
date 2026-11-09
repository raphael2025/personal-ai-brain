# Project Status

**Current phase:** Phase 0 — foundations  
**Release status:** pre-alpha; not suitable for production use or ingestion of sensitive personal archives.

This page distinguishes implemented code from planned architecture. A roadmap checkbox is not evidence that a capability works.

## Implemented and present in the repository

| Capability | Current state | Limitations |
|---|---|---|
| SHA-256 file identity | Implemented | Basic pre/post stat race check; broader filesystem edge cases remain |
| Directory discovery | Implemented | Read-only; records symlinks without intentionally traversing them; not a hardened sandbox against hostile concurrent filesystem changes |
| StorageRoot model | Implemented | In-memory validation only |
| AssetLocation model | Implemented | In-memory validation only; normalization policy still needs cross-platform review |
| CI | Implemented | Python 3.11–3.13 matrix; check latest run before relying on it |
| CodeQL | Implemented | Automated scan, not a security audit |
| Dependabot | Implemented | PRs still require compatibility review and passing checks |
| Contributor docs and templates | Implemented | Community process is still new |

## Not implemented yet

- Persistent asset registry and database migrations
- Storage-root enrollment UI or CLI
- Durable scan runs, checkpoints, and reconciliation
- Rename/move and duplicate-asset resolution
- Document, image, audio, video, archive, and code ingestion pipelines
- OCR, transcription, embeddings, lexical/vector retrieval
- Memory lifecycle, activation scoring, and progressive L0/L1/L2 loading
- Knowledge graph and conflict resolution
- Context planner, token budgeting, and multi-client API/MCP service
- Worker queue, leases, multi-node execution, and recovery
- Authentication, authorization, encryption, backup/restore, and external egress enforcement

## Security warning

Do not point the current scanner at hostile or attacker-writable filesystems and assume it is a security boundary. Do not expose any future API or parser service to a network until authentication, authorization, isolation, and resource limits are implemented and tested. External model egress is a design requirement, not yet an enforced runtime control.

## Validation policy

- CI must pass on the current commit before a change is considered validated.
- CodeQL success does not equal a complete security review.
- Performance targets require reproducible benchmarks with hardware, dataset, versions, and configuration recorded.
- Integrations remain experimental until their versions, licenses, update behavior, recovery behavior, and provenance have been tested.
