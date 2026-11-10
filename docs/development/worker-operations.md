# Local Worker Operations

**Status:** Initial local text extraction pipeline is wired end-to-end. The worker supports bounded UTF-8 text/Markdown/code extraction only.

## Prerequisites

- Apply migrations `0001_asset_registry.sql` through `0004_worker_root_grants.sql`.
- Install PostgreSQL support: `python -m pip install -e ".[postgres,dev]"`.
- Set `PAB_DATABASE_URL`.
- Register the storage root and complete a scan so the registry contains an available location and immutable asset version.
- Keep the worker mount map on the worker machine. It maps logical root UUIDs to local absolute mount paths; it is not part of the shared database.

## 1. Register the worker

Use a stable UUID for this worker:

```bash
pab worker register \
  --worker-id 00000000-0000-0000-0000-000000000001 \
  --name "local text worker" \
  --capability text
```

Grant access only to the storage roots this worker is allowed to read:

```bash
pab worker grant-root \
  --worker-id 00000000-0000-0000-0000-000000000001 \
  --root-id 00000000-0000-0000-0000-000000000002 \
  --actor operator
```

Grant and revoke operations are audited. Revocation blocks subsequent source resolution.

## 2. Configure local mounts

Copy [worker-mounts.example.toml](../examples/worker-mounts.example.toml) to a private local file, then replace the UUIDs and absolute mount path. The `worker_id` must match the registered worker.

For example:

```toml
version = 1
worker_id = "00000000-0000-0000-0000-000000000001"

[mounts]
"00000000-0000-0000-0000-000000000002" = "/mnt/pab/documents"
```

Do not put credentials in this file or in a storage-root URI. The worker ignores file paths supplied in job payloads and resolves paths from the Asset Registry after checking the worker grant and active job lease.

## 3. Enqueue a text extraction job

Find an asset version UUID using `pab asset inspect <asset-uuid>`, then enqueue it:

```bash
pab extract enqueue \
  --asset-version-id <asset-version-uuid> \
  --root-id <storage-root-uuid>
```

Enqueue is idempotent for the same root, asset version, extractor version, and configuration.

## 4. Run the worker

Process one compatible job and exit:

```bash
pab worker run \
  --worker-id 00000000-0000-0000-0000-000000000001 \
  --mounts-config /etc/pab/worker-mounts.toml \
  --once
```

Run continuously:

```bash
pab worker run \
  --worker-id 00000000-0000-0000-0000-000000000001 \
  --mounts-config /etc/pab/worker-mounts.toml
```

Ctrl+C and SIGTERM stop polling and allow the currently running handler to finish before the process exits. The runtime heartbeats its lease while the handler is active. The artifact publisher independently rechecks the lease generation and expiry before committing output.

## 5. Revoke access

```bash
pab worker revoke-root \
  --worker-id 00000000-0000-0000-0000-000000000001 \
  --root-id 00000000-0000-0000-0000-000000000002 \
  --actor operator
```

## Current limits

- The built-in handler accepts only the formats listed by `TextMarkdownExtractor` and enforces its 16 MiB input limit.
- Extracted text payloads are currently stored in PostgreSQL JSONB, not in a content-addressed blob store.
- The worker is a local foreground process; no Windows service installer, daemon supervisor, remote worker protocol, or desktop UI exists yet.
- A worker must be trusted to use only the configured mount map; OS-level sandboxing and per-worker database credentials are not yet implemented.
- For network/removable roots, configure the actual local mount path on the worker. The canonical registry stores only the logical storage URI.
