# Threat Model (Initial)

**Status:** initial working document; must be reviewed before production deployment.

## Assets to protect
- Original files and storage metadata
- Extracted text, OCR, transcripts, summaries, embeddings, and entity records
- User identity, connector credentials, model-provider keys, and access policies
- Query history, audit events, and backups

## Trust boundaries
1. User devices and removable storage
2. Control-plane API and database
3. Worker processes and parser libraries
4. Local model runtime and model gateway
5. Optional external model/provider APIs
6. Third-party AI clients connected through MCP or other adapters

## Threats and mitigations

| Threat | Initial mitigation | Required validation |
|---|---|---|
| Malicious documents exploit parsers | Isolated workers, resource limits, patched parsers | Malicious fixture suite and sandbox review |
| Prompt injection in retrieved content | Treat retrieved text as untrusted data, separate instructions from evidence | Adversarial retrieval tests |
| Accidental external disclosure | Egress deny by default, explicit per-class policy | Network-level egress tests |
| Unauthorized API/MCP access | No network exposure before authentication and authorization | AuthZ test matrix |
| Secrets leak through logs or commits | Secret-free examples, redaction, repository scanning | CI secret scanning |
| Source file changes during ingestion | Pre/post identity checks and immutable version records | Concurrent modification tests |
| Storage disappears during scan | Mark location unavailable; do not infer deletion | Disconnect/reconnect tests |
| Worker retries duplicate records | Idempotency keys and unique constraints | Repeated delivery tests |
| Database or host loss | Encrypted backups and tested restore procedure | Restore drills |
| Dependency compromise | Pin dependencies, review licenses and advisories | Automated dependency checks |

## Security invariants
- Source files are never modified by ingestion.
- No external model call occurs unless the user explicitly enables an applicable policy.
- Retrieved content cannot grant itself permissions or override system policy.
- A missing mount is not evidence that its files were deleted.
- Every derived artifact records its source version and processing implementation.
- Logs must not contain document bodies, secrets, or raw sensitive prompts by default.

This draft is not a completed security audit or production hardening certification.
