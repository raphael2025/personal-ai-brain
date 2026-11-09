# Contributing

Thank you for helping improve Personal AI Brain. The project is in Phase 0; design quality, safety, and reproducibility matter more than adding features quickly.

## Before opening a pull request

1. Search existing issues and discussions.
2. For substantial changes, open an issue describing the problem and proposed approach.
3. Keep changes focused and explain trade-offs.
4. Add or update tests for behavior changes.
5. Update documentation and architecture decision records when contracts or boundaries change.
6. Never include personal data, secrets, access tokens, private paths, or real user archives.

## Development expectations

- Python code should use type hints and clear module boundaries.
- Prefer small, testable interfaces over premature microservices.
- Workers must be idempotent, resumable, and safe under retries.
- Derived data must retain source identifiers and processing-version metadata.
- Do not mutate original user files.
- Do not claim an integration works until an automated or reproducible test demonstrates it.
- Pin dependencies and document license obligations for third-party components.

## Pull request checklist

- [ ] The change has a clear purpose and scope.
- [ ] Tests were added or updated.
- [ ] Documentation reflects the behavior.
- [ ] No secrets or personal data are included.
- [ ] Backward compatibility and migration impact are described.
- [ ] Security and privacy implications are considered.

## Design discussions

Use issues for bug reports and focused proposals. Include context, alternatives considered, expected behavior, and acceptance criteria. Large architecture changes should include an ADR under `docs/adr/`.
