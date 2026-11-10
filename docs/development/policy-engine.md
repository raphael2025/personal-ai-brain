# Deny-by-Default Policy Engine v1

**Status:** initial policy evaluator and PostgreSQL persistence are implemented. This is not yet an authenticated API or an external-model gateway.

## Security model

Authorization requires all of the following to match:

1. A registered, enabled principal.
2. The action appears in that principal's declared scopes.
3. A non-empty purpose is supplied.
4. An active grant matches the principal, action, purpose, exact data classification, and either an exact resource ID or an explicitly granted storage-root ID.
5. For egress, a separate grant must match the exact destination provider.

Unknown principals, disabled principals, missing purposes/resources, missing scopes, expired/revoked grants, provider mismatches, and evaluator errors deny. There is no implicit owner bypass, wildcard resource grant, or default cloud permission.

Principal scopes are only one gate; they do not independently authorize access. A matching active grant is also required. Resource and root identifiers are opaque UUIDs. A provider-specific egress grant contains only the egress action and one provider identifier. Purposes come from a fixed enum (assistant answer, personal search, memory confirmation, local extraction, external model egress, administration); arbitrary prompt text cannot be used as a purpose.

## Versioning and revocation

Every principal registration/disablement and grant create/revoke increments a singleton policy version. Authorization reads the policy version under a shared row lock and records its decision in the same transaction. Mutations take an exclusive lock on that row before changing policy state.

This serializes a revocation against authorization: an in-flight decision completes before the revocation transaction; every authorization started after the revocation commits observes the new version and revoked grant. A caller must re-authorize immediately before each external send; cached allow decisions must not be reused across policy versions.

## Audit and untrusted content

Policy decision and administrative audit tables are append-only. Decision rows contain only request/principal/action/resource/purpose/provider identifiers, allow/deny, reason code, matched grant ID, policy version, and time. Unknown action/purpose strings are normalized to safe fixed values/null before audit. They do not store document bodies, credentials, or prompt text.

Retrieved content is not an input to the policy evaluator. Files, OCR, code comments, web pages, tool outputs, and model outputs cannot grant scopes or modify policy. The repository accepts structured authorization metadata only.

## Current API

The Python repository supports:
- Principal registration and enable/disable.
- Scoped grant creation and revocation.
- Transactional authorization with a redacted decision audit.
- Deterministic in-memory evaluation for unit tests and isolated use.

The actor argument is audit metadata, not authentication. This repository does not authenticate administrators, users, workers, or providers. Do not expose these methods through an unauthenticated HTTP/MCP interface or treat the egress decision as proof that a provider request has been sent safely.

## Deliberate non-goals

No group/role inheritance, classification inheritance, automatic scope escalation, policy editor UI, context assembly, content redaction, cache implementation, model-provider adapter, or live network egress is included. The next integration step is to enforce policy before retrieval expansion and again for every evidence item before ContextBundle serialization or provider transmission.
