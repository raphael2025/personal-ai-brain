# ADR-0002: Modular monolith with independent workers

- **Status:** Accepted as initial implementation direction
- **Date:** 2026-11-09

## Context

The project needs clear module boundaries and background processing across machines, but premature microservices would increase deployment and debugging cost before domain contracts are stable.

## Decision

Start with a modular monolith for the API and core domain, plus independently runnable worker processes for discovery and ingestion. Define adapter interfaces around storage, parsers, retrieval backends, and model providers.

## Consequences

- Modules must not bypass domain interfaces through hidden cross-module database writes.
- Workers need idempotency keys, leases, retries, checkpoints, and observable failure states.
- Service extraction remains possible when scaling or isolation requirements are demonstrated.
