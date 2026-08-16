# Rta-Smriti Brain v0.4.0-alpha

This alpha turns repository memory from a manual snapshot into an operator-controlled living index while preserving local-first defaults.

## New

- Foreground `watch-repo` plus managed-background `watcher` lifecycle commands using incremental manifests
- Dashboard repository-sync controls with heartbeat, backend, and error visibility
- Persistent SHA-256 cache for repeated deep freshness checks
- Optional local hybrid FTS and vector retrieval
- Dependency-free deterministic hash embedding provider
- Lazy Sentence Transformers adapter for separately installed local models
- Pluggable regex, Tree-sitter, LSP-command, and entry-point parser registry
- Per-project source-size, parser, embedding, model, and ranking policy
- Dashboard controls with blocked-source and optional-provider warnings
- Canonical-root binding with explicit rebind protection and duplicate-root dashboard warnings
- Repository root, branch, HEAD, and dirty-file diagnostics
- Structured continuation checkpoints and one-click new-task prompts
- Claim provenance fields for source path, hash, verification command, timestamp, and status
- Compact anomaly-first deep freshness output with bounded details
- Default exclusions for worktrees, bundled browser runtimes, test scratch folders, and generated tool caches

## Fixed On Main

- Installed wheels now generate valid Python-module commands instead of pointing to repository-only source wrappers.
- `install-local` emits native `.cmd` launchers on Windows and executable POSIX launchers on macOS and Linux.
- Generated agent, MCP, dashboard, bootstrap, and context-pack commands use the active operating system's quoting and invocation rules.
- Setup no longer assumes the wrapper directory is already on `PATH`.
- Dashboard recovery guidance now distinguishes the foreground console from opt-in background repository sync.
- Windows, Ubuntu, and macOS CI build and smoke-test an installed wheel through bootstrap, retrieval, wrappers, MCP config, dashboard assets, and API authorization.
- Bootstrap now writes agent bridge files before the final index pass, so a newly created brain starts fresh instead of immediately reporting those generated files as added.

## Defaults And Boundaries

- SQLite remains local.
- No hosted account, cloud sync service, telemetry, privileged service, login item, or automatic reboot persistence is added.
- FTS5 and regex remain available deterministic defaults.
- The recommended bootstrap flow enables the dependency-free hash provider; lexical-only retrieval remains selectable and external embedding packages are never installed automatically.
- Sources above the selected cap remain blocked and keep freshness fail-closed.

See [Architecture](ARCHITECTURE.md) and [Usage Guide](USAGE_GUIDE.md).
