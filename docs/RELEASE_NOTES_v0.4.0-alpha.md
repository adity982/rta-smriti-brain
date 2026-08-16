# Rta-Smriti Brain v0.4.0-alpha

This alpha turns repository memory from a manual snapshot into an operator-controlled living index while preserving local-first defaults.

## New

- Foreground `watch-repo` plus managed-background `watcher` lifecycle commands using incremental manifests, event-scoped content hashing, and periodic polling verification
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
- Managed console start/open/status/restart/stop with stale-process, authorization, and occupied-port recovery
- One-command `start` onboarding for canonical-root detection, migration, indexing, watcher startup, console startup, and readiness proof
- Optional owner-controlled login startup on Windows, macOS, and Linux
- Evidence-aware Action Gate with typed policies, trust thresholds, expiry, path/action scope, required checks, owner overrides, and short-lived action/policy digest receipts
- Approximate call and test links plus bounded dependency, dependent, impact, evidence, and relevance graph queries with explicit relation semantics
- Retrieval diagnostics for provider, embedding coverage, parser fallback, freshness, rank components, latency, and source hashes
- Packaged public synthetic benchmark for no-memory, lexical, hash-hybrid, and explicitly optional Sentence Transformers retrieval plus stale, contradiction, continuation, and governance gates
- Explicit query-only local workspaces that search existing unlinked project-brain databases without merging or mutating them
- Selective redacted memory/checkpoint/policy export and integrity-checked import with rename, merge, or fail conflict handling
- Non-mutating selective bundle previews, bounded schema validation, staged all-or-nothing imports, and restrictive atomic private writes
- Authenticated HMAC-SHA256 local snapshots with consistent SQLite backup and tamper verification
- Cross-platform standalone CI artifacts with versioned filenames, full runtime smoke tests, and SHA-256 manifests
- Worktree-aware, frozen-binary-safe Git hooks with linked-file protection and atomic installation
- Opt-in managed post-commit checkpoint hooks that refuse to replace unknown hooks
- Operator memory feedback and conservative decay restricted to eligible old, unverified inference and hypothesis records
- Read-only-by-default, project-bound MCP capabilities with explicit write/ingestion flags, allowed thread roots, bounded frames/tasks, and downgraded agent provenance
- Descriptor-bound thread, bundle, snapshot, and repository reads; private SQLite modes and trusted-schema disablement
- Rendered Chromium operator acceptance configured for Windows, macOS, and Linux CI
- Isolated install, forced-upgrade/reinstall, and uninstall lifecycle proof
- Sanitized 100, 1,000, and 10,000-file indexing and retrieval resource evidence
- Destination-wide axe WCAG checks, accessible Intelligence and Bases tabs, explicit active-state
  semantics, live status announcements, modal focus containment/restoration, normal-mode contrast,
  reduced motion, forced-colors structure, and a zero-overlap mobile Canvas

## Fixed On Main

- Installed wheels now generate valid Python-module commands instead of pointing to repository-only source wrappers.
- `install-local` emits native `.cmd` launchers on Windows and executable POSIX launchers on macOS and Linux.
- Generated agent, MCP, dashboard, bootstrap, and context-pack commands use the active operating system's quoting and invocation rules.
- Setup no longer assumes the wrapper directory is already on `PATH`.
- Dashboard recovery guidance now distinguishes the foreground console from opt-in background repository sync.
- Windows, Ubuntu, and macOS CI build and smoke-test an installed wheel through bootstrap, retrieval, wrappers, MCP config, dashboard assets, and API authorization.
- Bootstrap now writes agent bridge files before the final index pass, so a newly created brain starts fresh instead of immediately reporting those generated files as added.
- Unsigned selective-bundle imports now downgrade memories and quarantine checkpoints and policies instead of inheriting authority.
- The release privacy gate now suppresses only exact hashed detector-definition lines; unrelated private paths in those modules fail the scan.
- Generated PowerShell and POSIX commands now keep substitutions, variables, backticks, quotes,
  apostrophes, and embedded newlines literal instead of allowing a project path to alter the command.
- Disposable operator QA uses a random per-launch capability token and proves that the retired fixed
  token is rejected.
- Post-bootstrap project selection now binds the exact project/database tuple, rejects ambiguous
  same-name roots, and clears a previous selection when the identity verification refresh fails.

## Defaults And Boundaries

- SQLite remains local.
- No hosted account, cloud sync service, telemetry, privileged service, login item, or automatic reboot persistence is added.
- FTS5 and regex remain available deterministic defaults.
- The recommended bootstrap flow enables the dependency-free hash provider; lexical-only retrieval remains selectable and external embedding packages are never installed automatically.
- Sources above the selected cap remain blocked and keep freshness fail-closed.
- Call relationships are approximate impact hints, not compiler-perfect call graphs.
- Workspaces reference local brain database paths and do not combine project stores.
- Selective bundles exclude source code by default; snapshots contain the complete local brain and should remain private.
- Selective bundles provide SHA-256 integrity but no sender authentication; inputs are capped at 25 MB.
- HMAC snapshots use a local shared secret and are authenticated, not encrypted or public-key signed.
- Snapshot payloads are capped at 64 MiB, with legacy envelopes capped at 16 MiB.
- The bundled benchmark is a transparent regression harness, not independent evidence of competitive superiority.

See [Architecture](ARCHITECTURE.md) and [Usage Guide](USAGE_GUIDE.md).
