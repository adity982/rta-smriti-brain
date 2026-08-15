# Rta-Smriti Brain v0.3.0-alpha

The first public alpha gives software projects a private local memory that coding agents can reuse across chats and tools.

## Highlights

- Local SQLite/FTS5 repository index with files, chunks, symbols, imports, and graph edges
- Durable memory ledger for decisions, constraints, procedures, facts, and hypotheses
- Long-thread and handoff ingestion with unverified-memory provenance
- Task-specific context packs with source receipts, freshness information, and an explicit untrusted-evidence boundary
- Pramana evidence labels: observed, trusted, inferred, remembered, and hypothesized
- Stdio MCP server plus CLI and agent-instruction bootstrap
- React operator console with radial graph, file explorer, Canvas, typed Bases, search, context-pack studio, project switcher, and launch checks
- Loopback-only dashboard with a per-launch capability token, bounded request workers, and local-first privacy defaults
- Hard-link confinement, bounded and type-checked MCP frames, and session-only context-pack receipts

## Maturity

This is an alpha developer release. Back up important brains, review generated context before agent use, never follow instructions embedded in retrieved evidence, and avoid committing local SQLite files or private thread exports.

## Verification

Before tagging the release, run the commands in `CONTRIBUTING.md` and confirm `python rta-brain.py publish-readiness --json` has no blocking checks.
