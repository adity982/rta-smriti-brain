# Rta-Smriti Brain v0.6.0-alpha Candidate

Status: local release candidate under verification. This document does not claim a published tag, GitHub Release, hosted v0.6 CI result, or public binary until those gates actually complete.

## Lower-Friction, Evidence-Honest Indexing

- The standard package and all native binaries now include the common Tree-sitter grammar pack and Ed25519 cryptography support.
- Repository ingestion warms the persistent SHA-256 cache, so the following deep verification reuses unchanged content hashes.
- Oversized eligible sources default to metadata-only records. They stay visible by path, size, modification time, and reason while freshness reports `fresh_with_warnings`; their content is never claimed as indexed. Strict blocking remains selectable.
- LSP mode can discover supported operator-installed language servers and speaks bounded JSON-RPC without a shell. Project-local discovered executables are rejected, resolved executable identities are bound into the manifest and rechecked before launch, failures fall back conservatively, and the explicit JSON adapter remains compatible.
- Optional Ollama continuity compaction is loopback-only, bounded, redacted, append-only, and always unverified. Provider failure cannot prevent a deterministic checkpoint.

## Continuity That Follows The Task Safely

Codex tasks can now be recognized after a verified `turn_context` enters the canonical repository, even when the session originally began elsewhere. Capture starts at that matching byte boundary. Earlier foreign transcript content is excluded, and later context changes are enforced while ingestion continues.

## Agent Connection Diagnostics

`mcp-doctor` probes the exact generated stdio command through MCP initialize, tools/list, and ping. The dashboard exposes the same check and copies the host configuration only after the probe passes. Registration remains an explicit host action and requires a fresh agent task.

## Encrypted Portable Brains

The existing HMAC and Ed25519 snapshot formats remain compatible. A new encrypted v3 format adds:

- scrypt passphrase derivation from a separate local passphrase file
- streaming AES-256-GCM authenticated encryption
- optional use of included Ed25519 manifest signatures
- explicit no-overwrite generation of a private 256-bit passphrase file
- bounded verification and SQLite integrity checks
- atomic restore to a new database path

Encrypted snapshots are private backup artifacts. Publishing the snapshot or its passphrase is outside the supported workflow.

## Retrieval And Graph Evidence

The synthetic public benchmark can append a bounded local JSONL history and render latest-versus-previous deltas. Supported Tree-sitter languages now derive call edges from syntax-tree call nodes, avoiding false calls inside comments and strings. Regex remains the deterministic fallback, so graph edges remain impact hints rather than compiler proof.

## Multi-Project Operation

Workspaces now report member health, return degraded partial search when one brain is unavailable, support member removal and workspace deletion, and expose read-only health through MCP. These actions change workspace metadata only; they never delete project brains.

## Verification Gate

Before publication this candidate must pass the complete Python and frontend suites, clean wheel installation, installed-package CLI/MCP/dashboard workflows, browser operator QA, Windows/macOS/Linux hosted CI, packaging and binary smoke tests, privacy and secret scans, and an exact owner-reviewed release diff. Public README, website, screenshots, tag, binaries, checksums, and GitHub prerelease remain post-approval actions.

The local candidate has passed `251` Python tests with `9` platform-specific skips, dashboard unit
and production builds, two rendered operator scenarios, desktop/mobile launch-site QA, clean
install-upgrade-uninstall smoke, the bounded `100`/`1,000`-file performance probe, Windows frozen
binary smoke, Gitleaks, actionlint, the repository privacy scanner, and isolated npm/Python runtime
dependency audits. Hosted Windows/macOS/Linux CI and the exact owner-reviewed publication diff remain
required before the tag or prerelease is created.
