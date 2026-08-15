# Rta-Smriti Brain v0.4.0-alpha

This alpha turns repository memory from a manual snapshot into an operator-controlled living index while preserving local-first defaults.

## New

- Foreground `watch-repo` command using incremental manifests
- Persistent SHA-256 cache for repeated deep freshness checks
- Optional local hybrid FTS and vector retrieval
- Dependency-free deterministic hash embedding provider
- Lazy Sentence Transformers adapter for separately installed local models
- Pluggable regex, Tree-sitter, LSP-command, and entry-point parser registry
- Per-project source-size, parser, embedding, model, and ranking policy
- Dashboard controls with blocked-source and optional-provider warnings

## Fixed On Main

- Installed wheels now generate valid Python-module commands instead of pointing to repository-only source wrappers.
- `install-local` emits native `.cmd` launchers on Windows and executable POSIX launchers on macOS and Linux.
- Generated agent, MCP, dashboard, bootstrap, and context-pack commands use the active operating system's quoting and invocation rules.
- Setup no longer assumes the wrapper directory is already on `PATH`.
- Dashboard recovery guidance now explains the foreground process and one-session capability URL.
- Windows, Ubuntu, and macOS CI build and smoke-test an installed wheel through bootstrap, retrieval, wrappers, MCP config, dashboard assets, and API authorization.

## Defaults And Boundaries

- SQLite remains local.
- No hosted account, sync service, telemetry, or background daemon is added.
- FTS5 and regex remain the defaults.
- Optional parsers and embeddings are never silently enabled.
- Sources above the selected cap remain blocked and keep freshness fail-closed.

See [Architecture](ARCHITECTURE.md) and [Usage Guide](USAGE_GUIDE.md).
