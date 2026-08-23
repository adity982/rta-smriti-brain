# Rta-Smriti Brain v0.9.0-alpha

`v0.9.0-alpha` is the Universal Capture prerelease. It joins canonical project
identity, bitemporal truth, governed context compilation, and private
agent-session capture into one local, inspectable continuity system.

## Universal Capture

- Opt-in adapters normalize supported Codex, Claude Code, Cursor, GitHub
  Copilot, Gemini CLI, and generic local events into one versioned schema.
- Private bounded spools isolate producers from SQLite and apply explicit
  backpressure, recovery, quarantine, and receipt policies.
- One managed normalizer daemon per brain records append-only, hash-chained
  events with project, checkout, session, causal, privacy, and policy anchors.
- Metadata-only, continuity, and explicitly granted encrypted forensic profiles
  keep raw payload retention off by default.

## Continuity And Governance

- Causal replay reports interruption, incomplete spans, gaps, late events, and
  the latest trusted cursor without executing captured actions.
- Interactive retention, redaction, and deletion are preview-first, require a
  separate destructive capability, and bind confirmation to the exact policy,
  cutoff or scope, affected state, and operator. Background retention enforces
  only the already-authorized immutable policy.
- Agent-hook installation is preview-first, reversible, canonical-root-bound,
  and separated from read-only MCP and dashboard capabilities.
- Captured text remains untrusted evidence. It cannot promote itself to project
  truth, policy, approval, or verified memory.
- The multi-project MCP gateway is project-scoped and read-only; all mutation
  classes require an explicit single-project binding.
- Replay reads event content and deletion tombstones from one database snapshot;
  default MCP diagnostics verify a bounded journal prefix and report whether the
  verification is complete. Routine capture-write grants can pause or resume a
  source but cannot irreversibly remove it.
- Capture redaction covers root-level Windows and POSIX absolute paths before
  default read-only MCP responses are emitted.
- Project-bound status reports include only that project's spool occupancy and
  omit database-wide daemon activity counters and global session-binding
  diagnostics.
- Login supervision revalidates every private enrollment receipt against the
  brain's current canonical project root before starting any enrolled worker.
- Shared free-text redaction recognizes provider credentials including Google
  API keys and Stripe secret or webhook keys before spool, journal, replay, and
  export verification.
- Default MCP continuity and readiness reads use a strict path-free lifecycle
  projection: local roots, database paths, process identifiers, launch material,
  and raw errors remain private while a bounded `has_error` signal preserves
  fail-closed readiness.
- Managed continuity workers bind liveness to both PID and cross-platform
  process-birth identity. A confirmed mismatch is stale and recoverable without
  signaling the unrelated process; an unavailable identity fails closed rather
  than risking a duplicate worker.
- Continuity start/stop is an independent MCP process-control capability rather
  than an implicit side effect of memory-write permission, and control responses
  use the same path-free lifecycle projection as status and readiness reads.
- Capture export and replay verify normalized content, event envelopes, every
  hidden privacy-filtered chain link, and the pagination anchor before returning
  a page. Receipts label the bounded verification scope instead of implying a
  full-journal proof.
- Rendered operator acceptance parses the downloaded export and verifies its
  schema, journal proof, redaction proof, payload exclusion, canonical-path
  exclusion, and provider-credential exclusion rather than checking only its
  filename.
- The package README, CLI inventory, installation guide, verification record,
  and website identify v0.9 consistently and link to the same formal prerelease.

## Qualification Contract

The frozen source candidate passed:

- 760 Python tests, with 23 explicit optional-dependency or privilege skips and
  649 subtests on Windows;
- dashboard unit tests plus the complete rendered Playwright operator journey;
- the dedicated Universal Capture operator journey, including parsed export
  integrity and privacy assertions;
- installed-wheel upgrade and uninstall checks from `0.8.0a1` to `0.9.0a1`;
- Windows native CLI, SQLite/FTS, MCP, benchmark, bundled Tree-sitter,
  Universal Capture, encrypted snapshot, Ed25519, sync, and console smoke tests;
- the 10,000-event capture probe at 170.445 events per second, with 43.071 ms
  p99 replay-page latency and verified fail-closed backpressure;
- repository and artifact privacy scans, Gitleaks history and working-tree
  scans, actionlint, npm audit, Python dependency audit, wheel inspection, and
  checksum verification; and
- hosted CI on Windows, macOS, and Ubuntu across Python 3.11, 3.12, and 3.13.

A later Codex Deep Security Scan coordinator attempt did not inspect the
workspace because both workers were blocked, and its completion call rejected a
non-UUID scan identifier. It therefore produced no usable sealed report and is
not represented as security coverage. Release confidence instead rests on the
completed code-specific security tests, threat-model controls, Gitleaks,
dependency audits, privacy scans, and cross-platform hosted matrix documented in
the [verification record](RELEASE_VERIFICATION.md).

Tag-generated binaries, wheel, SBOMs, and checksums are accepted only after the
native workflow passes and downloaded assets match the combined manifest. Any
code or release-relevant content change invalidates the affected evidence and
requires proportionate reruns.
