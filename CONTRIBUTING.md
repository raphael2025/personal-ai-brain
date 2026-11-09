# Contributing

Personal AI Brain is pre-alpha. The [System Blueprint](docs/architecture/system-blueprint.md) defines the target architecture; the [Implementation Map](docs/development/implementation-map.md) defines work packages, dependencies, and acceptance criteria. Read both before proposing a substantial feature.

## Before opening a PR

1. Search existing issues and discussions.
2. Select a work package from the Implementation Map or open a focused design issue.
3. Keep changes scoped to one module or contract.
4. Add contract, failure, and regression tests.
5. Update docs and ADRs when interfaces or trust boundaries change.
6. Never include personal data, secrets, access tokens, private paths, or real user archives.

## Architecture rules

- Follow the dependency direction in Module Contracts.
- Keep domain logic independent of frameworks, ORM models, and vendor SDKs.
- Prefer a modular monolith and ports/adapters; do not introduce microservices without evidence.
- Original files are read-only; derived data retains source/version provenance.
- Workers must be idempotent, resumable, resource-bounded, and safe under retries.
- Incomplete scans must never imply deletion.
- Retrieval cannot bypass policy; external egress is deny-by-default.
- Treat retrieved content and tool output as untrusted data.
- Proposed integrations must not be described as working until tested.

## Good first contributions

- Registry service methods and transaction tests.
- Job/lease state machine and fencing tests.
- One isolated document extractor.
- Synthetic evaluation corpus and labelled queries.
- BM25 retrieval adapter and reproducible benchmark.
- Deny-by-default policy evaluator with negative tests.

Do not start with UI, a graph database, or a model-provider integration before the underlying contracts are stable.

## PR checklist

- [ ] Scope maps to an issue/work package.
- [ ] Tests cover success and failure paths.
- [ ] Documentation and status reflect actual behavior.
- [ ] No secrets or personal data.
- [ ] Migration and rollback impact described.
- [ ] Security/privacy implications reviewed.
- [ ] CI passes on supported Python/database versions.

Large architecture changes require an ADR under docs/adr/.
