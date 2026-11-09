# Asset Registry Service and CLI

**Status:** initial application service implementation in PR review. PostgreSQL schema is merged; service behavior is not production-certified until this PR and its CI are merged.

## Install

Install the package with its PostgreSQL extra:

    python -m pip install -e ".[postgres,dev]"

Set the connection string in the environment. Do not commit it or put it in shell history:

    export PAB_DATABASE_URL='postgresql://...'

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
4. Stores scan observations, logical asset IDs, immutable content versions, and locations in one transaction.
5. Marks the scan COMPLETE, PARTIAL, or FAILED.
6. Calls database reconciliation only for COMPLETE scans.

A file that changes or becomes inaccessible between discovery and hashing makes the scan PARTIAL. Partial and failed scans never infer missing locations. Identical bytes at two different paths create separate logical assets; content fingerprints are not automatic merge authority.

## Important limitations

- The initial service uses path-based file reopening for hashing after descriptor-relative discovery. It detects metadata/content changes during hashing and refuses symlinks, but it is not a complete sandbox against hostile concurrent directory replacement. Do not treat it as a security boundary for adversarially mutable roots; see the scanner threat model and Issue #12.
- Network roots require an operator-provided local mount path. No SMB/NFS client, mount management, or remote credential storage is included.
- A process crash can leave a scan in RUNNING. Durable scan/job recovery and worker leases are follow-up work.
- The CLI currently supports root enrollment/listing and scanning. Asset browsing, scan resume, dry-run reconciliation, and explicit normalizer migration are follow-up work.
- The migration must be applied before using the CLI. The CLI does not auto-run migrations.

## Safety

Original files are never written, renamed, or deleted. PAB_DATABASE_URL is loaded at runtime and is not logged. The service fails if the root is disabled, unknown, or requires an explicit mount path. A complete empty scan can mark previously known paths missing; therefore only enroll roots whose full scan scope is accessible and intended.
