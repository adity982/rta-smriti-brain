# Rta-Smriti Brain v0.6.1-alpha Candidate

`v0.6.1-alpha` is a local release candidate. It is not yet tagged, published, or represented as the latest public release.

## Canonical Integrity

- Adds a per-checkout identity so clones and Git worktrees cannot borrow another checkout's freshness.
- Fails closed when `stale-check`, `self-check`, operational readiness, MCP startup, or an already-running root-pinned MCP process observes the wrong checkout.
- Validates stored binding identity during freshness checks even when callers omit an active root.
- Adds privacy-safe integrity diagnostics to the CLI, MCP, and operator console.
- Detects duplicate ownership of one canonical root within a database and across dashboard-discovered brain files.
- Records schema version 7 and bounded migration receipts containing fingerprints rather than local paths.

## Safe Root Migration

- Replaces legacy rebind switches with `root-rebind PATH --backup PATH`.
- Requires the destination to match the stored repository lineage.
- Refuses migration while watcher or continuity workers still own the old checkout.
- Refuses silent relocation through project initialization or ordinary ingestion, including when the former root no longer exists.
- Uses a cross-process binding gate and MCP process/call leases so migration cannot race tool dispatch.
- Creates a no-clobber SQLite backup, verifies its integrity, and returns a streamed SHA-256 digest.
- Applies the new root, checkout identity, migration receipt, and forced reindex in one transaction; failures roll back the live brain.
- Rechecks the pre-scan project binding after acquiring the SQLite write lock so a stale concurrent ingest cannot repopulate an old checkout.

## Security And Privacy

- Verifies Git metadata layouts and checkout backlinks before writing repository or checkout markers, preventing crafted `.git` aliases from redirecting writes into another valid repository.
- Builds backups at a private unpredictable sibling path and publishes them atomically without overwriting an existing destination.
- Rejects linked or reparse-point local identity directories.
- Omits raw project names, roots, branch names, and backup paths from shareable diagnostics and migration receipts.
- Keeps backups local and private; they contain the full brain database and must never be committed or published.

## Upgrade Notes

Existing databases migrate in place when opened. Before upgrading a consequential brain, create a private backup. Regenerate and re-register single-project MCP configuration after migration so the server receives its pinned `--root`; a running agent host cannot acquire changed MCP configuration dynamically.

The latest public prerelease remains `v0.6.0-alpha` until this candidate completes local, hosted, cross-platform, operator, packaging, security, and owner-approval gates.
