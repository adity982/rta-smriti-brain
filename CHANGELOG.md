# Changelog

## Unreleased

- Added bounded Codex `turn_context` rebinding so a task started elsewhere can be captured after it enters the canonical project, without importing the earlier foreign transcript.
- Added an MCP doctor that probes the exact generated stdio command through initialize, tools/list, and ping before host registration.
- Added AES-256-GCM encrypted portable snapshots with scrypt passphrase derivation, optional Ed25519 sender signatures, authenticated verification, and atomic restore to a new brain.
- Added append-only benchmark history, latest-versus-previous metric deltas, and historical Markdown reporting.
- Replaced regex-derived Tree-sitter call edges with language-aware syntax-tree call extraction for Python, JavaScript, TypeScript, TSX, Go, Rust, and Java.
- Added workspace member health, degraded partial search, member removal, workspace deletion, and a read-only MCP health tool.
- Added dashboard operator workflows for MCP probing, workspace health/member management, and encrypted snapshot key generation, create, verify, and restore.
- Moved common Tree-sitter grammars and Ed25519 support into the standard package and native binary contract.
- Added metadata-only oversized-source isolation with explicit `fresh_with_warnings` semantics and a compatible strict-block policy.
- Added opt-in discovery and bounded native JSON-RPC for supported local language servers, with project-local executable rejection and conservative parser fallback.
- Added opt-in loopback-only Ollama continuity compaction with redaction, request/response bounds, append-only provenance, and unverified derived-state labeling.
- Added release regressions proving that completed ingestion warms every eligible SHA-256 cache entry before a deep verification.

All notable changes are documented here. The project follows semantic versioning while APIs remain alpha.

## [0.5.0-alpha] - 2026-08-20

- Added append-only Codex session events, resumable transcript cursors, structured work-state reconciliation, and operational readiness.
- Added a managed continuity daemon with canonical-project session binding, partial-write recovery, payload redaction/bounds, heartbeat validation, and conservative automatic checkpoints.
- Added dashboard and MCP lifecycle controls plus one fail-closed multi-project MCP gateway.
- Added optional Ed25519 public-key snapshot signatures and cross-platform snapshot key generation while keeping HMAC snapshots compatible.
- Added shareable Markdown output for the public benchmark.
- Added continuity binding diagnostics that explain when recent Codex sessions exist outside the canonical project root without exposing foreign paths.

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
