# Asset Registry Service and CLI

**Status:** initial application service and CLI are merged in PR #34. PostgreSQL 16 integration tests, Python 3.11–3.13 CI, CodeQL, and Secret Scanning passed. This remains a pre-alpha developer preview, not production-certified.

## Install

Install the package with its PostgreSQL extra:

    python -m pip install -e ".[postgres,dev]"

Set the connection string in the environment. Do not commit it or put it in shell history:

    read -rsp "PAB_DATABASE_URL: " PAB_DATABASE_URL; echo; export PAB_DATABASE_URL

Apply the migration once to the target database:

    psql "$PAB_DATABASE_URL" -v ON_ERROR_STOP=1 -f infrastructure/postgres/migrations/0001_asset_registry.sql

## Enroll a root

Enrollment is explicit. The URI is the logical source identity; it is not automatically discovered from the host.

    pab root add --name "Laptop Documents" --uri "file:///home/user/Documents" --kind local --case-sensitive yes
    pab root list

The --case-sensitive option accepts yes, no, or unknown. Unknown uses exact path comparison. The selected normalizer version is stored with the root and copied to each scan. Changing it later requires an explicit location-key migration; the repository refuses to scan while active locations use a different version.

## Scan

    pab scan <root-uuid>

For an SMB/NFS root, supply the mounted path on this host:

    pab scan <root-uuid> --path /mnt/nas/private

The override is used only for this scan; it does not replace the logical URI stored in the registry. Direct SMB/NFS protocol access is not implemented by this initial scanner.

The service:
1. Creates a RUNNING scan record.
2. Runs read-only directory discovery.
3. Hashes discovered regular files with SHA-256.
4. Stores scan observations, logical asset IDs, immutable content versions, and locations in one transaction; replaying an identical finalization is idempotent, while a conflicting replay is rejected.
5. Marks the scan COMPLETE, PARTIAL, or FAILED.
6. Does **not** automatically mark unseen locations missing. Reconciliation is a separate operator action, available only for COMPLETE scans and recorded in audit_events.

A file that changes or becomes inaccessible between discovery and hashing makes the scan PARTIAL. Partial and failed scans never infer missing locations. Identical bytes at two different paths create separate logical assets; content fingerprints are not automatic merge authority.

## Important limitations

- Hashing uses descriptor-relative opens beneath the configured root, O_NOFOLLOW on each path component, discovery-metadata checks, and before/after file-descriptor checks. It fails closed when the platform lacks the required primitives. This prevents symlink traversal during the hash phase, but it is not a complete sandbox against every hostile concurrent rename pattern; see the scanner threat model and Issue #12.
- Network roots require an operator-provided local mount path. No SMB/NFS client, mount management, or remote credential storage is included.
- A process crash can leave a scan in RUNNING. Durable scan/job recovery and worker leases are follow-up work.
- The CLI supports root enrollment/listing, scanning, scan history, asset list/inspect, reconciliation preview/apply, and path-normalizer migration preview/apply. Scan resume and crash recovery remain follow-up work.
- Reconciliation is deliberately two-step: run `pab reconcile preview <scan-id>` first, then `pab reconcile apply <scan-id> --actor <identity>` only after reviewing the candidates. Preview is read-only; apply requires a COMPLETE scan and writes an audit event.
- Path-normalizer migration is also two-step. Preview lists every active path-key change and any collision. Apply is blocked by running scans, refuses all collisions, updates only active locations, updates the root version, and records an audit event in the same transaction. Historical scan observations and closed location history remain unchanged.
- The migration must be applied before using the CLI. The CLI does not auto-run migrations.

## Safety

Original files are never written, renamed, or deleted. PAB_DATABASE_URL is loaded at runtime and is not logged. The service fails if the root is disabled, unknown, or requires an explicit mount path. A complete empty scan does not change location availability until an operator explicitly applies reconciliation. Review the dry-run candidate list before applying it.


## Operator inspection commands

    pab scan-status --root-id <root-uuid> --limit 50
    pab asset list --root-id <root-uuid> --limit 100
    pab asset inspect <asset-uuid>
    pab reconcile preview <scan-uuid>
    pab reconcile apply <scan-uuid> --actor operator-name

The preview lists active locations that would become missing. It does not write registry rows. The apply command refuses non-COMPLETE scans, performs reconciliation in a database transaction, and records the actor and outcome in `audit_events`. Treat the actor as an operator identity, not as a password or secret.


## Path-normalizer migration

    pab root migrate-normalizer <root-uuid> --target-version v1-casefold
    pab root migrate-normalizer <root-uuid> --target-version v1-casefold --apply --actor operator-name

The first command is a read-only preview. Inspect every path and collision before applying. If two active paths map to the same target key (for example, `Docs/Readme.md` and `docs/readme.md` under case-folding), the migration refuses to proceed; it never merges assets or chooses a winner. The apply transaction updates active locations, changes the root's normalizer version, and writes the audit event together. If any step fails, all updates roll back. A pending or running scan blocks migration.
