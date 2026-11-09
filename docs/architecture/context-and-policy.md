# Context, Permissions, and External Egress

**Status:** proposed security contract. Retrieval without authorization is unacceptable.

## Principals and resources

Principals include the human user, local application, AI client, worker identity, and service identity. Each has explicit scopes and an owner. Resources include roots, assets, versions, artifacts, memories, search results, and ContextBundles.

Each resource carries owner, data classification, source/root relationship, permitted processing locations, permitted purposes, and optional expiry/retention. Initial classifications: PUBLIC, PERSONAL, SENSITIVE, RESTRICTED. Derived artifacts inherit source classification; classification may be raised but not silently lowered.

## Authorization

- Default deny.
- Deny when principal, purpose, classification, or policy is missing/unknown.
- A connector cannot widen its own scopes.
- A model provider is a destination principal and needs a separate egress decision.
- Workers use their service identity, not user-facing scopes.
- Policy evaluation errors fail closed.
- Candidate discovery may use only metadata the caller can discover; content expansion requires a second authorization check.

## External model egress

A grant specifies provider/model endpoint, purpose, allowed classifications, root/asset scope, provider retention conditions, expiry, and revocation behavior. Default is OFF. A generic allow-cloud-AI boolean is insufficient.

Before transmission:
1. Verify destination provider identity.
2. Re-evaluate policy for every evidence item.
3. Remove denied items and rebuild citations.
4. Apply redaction and byte/token budget.
5. Record policy version and decision.
6. Send only the approved serialized bundle.
7. Record provider request ID/outcome without full content.

Any failed step blocks transmission.

## Untrusted content

Retrieved files, metadata, OCR, code comments, web pages, tool results, and model outputs are untrusted data. They cannot modify policy, grant scopes, change principal, or authorize egress. Keep quoted evidence structurally separate from instructions.

## Audit events

Minimum fields: event ID/time, actor principal, action, resource type/ID, purpose, decision/reason, policy version, request/correlation ID, destination provider for egress, outcome, safe metadata. Never store full documents, credentials, or raw sensitive prompt payloads.

## Required security tests

Unknown principal denied; missing purpose denied; policy outage denied; unauthorized candidate never expanded; denied evidence absent from ContextBundle; egress denied by default; provider mismatch blocks send; revocation applies before next send; prompt injection cannot alter policy; cache keys include principal and policy version; logs contain no source body or secret.
