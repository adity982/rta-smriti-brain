# Changelog

All notable changes are documented here. The project follows semantic versioning while APIs remain alpha.

## [0.4.0-alpha] - Unreleased

- Added a foreground incremental repository watcher and persistent stat-keyed SHA-256 cache.
- Added optional hybrid FTS and local-vector retrieval with dependency-free hash embeddings and a lazy Sentence Transformers adapter.
- Added a parser registry with deterministic regex, optional Tree-sitter, explicit LSP command, and Python entry-point adapters.
- Added per-project ingestion policies for parser choice, retrieval provider, semantic weight, and source-file size caps up to 16 MB.
- Added authenticated loopback settings APIs and dashboard controls with explicit blocked-file and optional-dependency warnings.
- Added canonical-root protection, Git checkout diagnostics, structured continuation checkpoints, claim provenance, compact freshness output, and generated-artifact exclusions.
- Added a one-click new-task prompt to the dashboard and MCP/CLI continuation tools.
- Made the recommended bootstrap dependency-free hybrid retrieval with deterministic hash embeddings; lexical-only mode remains selectable.
- Fixed bootstrap ordering so generated agent bridge files are included in the initial index and a new brain starts fresh.

## [0.3.0-alpha] - 2026-08-15

- Added multi-project React operator console and radial semantic graph.
- Added file explorer, Canvas, typed Bases, context-pack receipts, memory ledger, freshness, and bootstrap flow.
- Added agent-neutral targets and stdio MCP integration.
- Added launch site, privacy-safe Atlas demo, Product Hunt assets, social preview, and editable Remotion demo video.
- Added per-launch dashboard capability authentication, bounded HTTP workers, strict MCP frame validation, and hard-link rejection.
- Added explicit untrusted-evidence boundaries to every generated context pack.
- Made context-pack receipts session-only and expanded path masking across display and bootstrap surfaces.
- Split GitHub Pages build and deployment privileges, pinned actions by commit, and added deterministic plus Gitleaks privacy gates.
