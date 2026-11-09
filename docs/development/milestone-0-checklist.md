# Milestone 0 — Acceptance Checklist

This checklist is intentionally strict. The project remains in Phase 0 until these gates have evidence.

## Repository and CI
- [x] Public repository and contribution policy
- [x] Initial CI workflow
- [ ] CI run observed passing on GitHub
- [ ] Dependency lock and supported Python matrix
- [ ] Secret scanning and dependency review

## Asset identity and discovery
- [x] Initial streaming SHA-256 identity primitive
- [ ] Unit tests executed in CI
- [ ] Storage-root model and validation
- [ ] Safe scanner that never follows unsafe links by default
- [ ] Scan-run state and incomplete-scan semantics
- [ ] Reconciliation for move/rename/duplicate observations
- [ ] Unavailable-volume and permission-denied tests

## Memory/retrieval evaluation
- [x] Initial evaluation plan
- [ ] Synthetic, redistributable benchmark corpus
- [ ] Human-labelled query set and gold source references
- [ ] Baseline retrieval implementation
- [ ] Comparative evaluation reports

## Security
- [x] Initial threat model
- [ ] Authentication and authorization design
- [ ] External egress policy implementation
- [ ] Parser isolation and resource limits
- [ ] Backup/restore test

## Exit criteria
A checklist item is complete only when code or documentation exists and the corresponding test/evidence is linked. No performance or security claim may be made without reproducible evidence.
