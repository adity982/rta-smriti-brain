# Changelog

## Unreleased

- Added append-only Codex session events, resumable transcript cursors, structured work-state reconciliation, and operational readiness.
- Added a managed continuity daemon with canonical-project session binding, partial-write recovery, payload redaction/bounds, heartbeat validation, and conservative automatic checkpoints.
- Added dashboard and MCP lifecycle controls plus one fail-closed multi-project MCP gateway.
- Added optional Ed25519 public-key snapshot signatures and cross-platform snapshot key generation while keeping HMAC snapshots compatible.
- Added shareable Markdown output for the public benchmark.
- Added continuity binding diagnostics that explain when recent Codex sessions exist outside the canonical project root without exposing foreign paths.

All notable changes are documented here. The project follows semantic versioning while APIs remain alpha.

## [0.4.0-alpha] - Unreleased

- Added foreground and managed-background incremental repository sync with optional filesystem events, portable polling fallback, lifecycle status, heartbeat, and a persistent stat-keyed SHA-256 cache.
- Made repository refresh transactional so parser or indexing failures cannot leave a partial new snapshot visible.
- Added bounded concurrent MCP request scheduling so control traffic remains responsive while mutations preserve causal order.
- Expanded optional Tree-sitter extraction for Python, TypeScript, Go, Rust, and Java symbols and imports.
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
