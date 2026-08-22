# Rta-Smriti Brain v0.8.0-alpha Candidate

`v0.8.0-alpha` is an uncommitted local candidate. It is not tagged, published,
or represented as the latest public release.

## Cognitive Context Compiler

- Adds strict, immutable agent profiles and operator-authorized task contracts.
- Compiles objective, acceptance criteria, evidence requirements, stop and
  escalation conditions, prohibited repetition, privacy scope, informational
  grants, and token economics into a bounded agent context.
- Supports explicit minimal, balanced, investigative, and handoff variants from
  one verified snapshot.
- Explains inclusion, omission, redaction, downgrade, deduplication, section
  allocation, contradiction handling, and budget truncation through immutable
  metadata receipts.
- Records bounded operator-confirmed outcomes and candidate attribution without
  letting the compiler execute work.

## Authority And Privacy

- Binds short-lived capabilities to project, contract, principal, session,
  scope, expiry, and append-only revocation state.
- Protects the host authority key with Windows DPAPI or an owner-only POSIX file;
  status exposes only a fingerprint.
- Filters unauthorized scope and privacy classes before scoring and keeps
  excluded identities opaque.
- Uses server-owned agent identity for MCP and the same compiler boundary across
  CLI, loopback console, and MCP.
- Preserves the product boundary: context preparation and evidence explanation,
  never tool execution, model routing, orchestration, or publication.
- Extends the privacy gate to reject missing or empty artifact roots, links,
  reparse points, and special files; recursively inspect bounded wheel, ZIP,
  nested ZIP, and renamed ZIP containers from stable bytes; and enforce
  platform-neutral paths plus scan-wide resource budgets.
- Reuses one fail-closed repository identity and Git-state inspection across
  brain databases bound to the same canonical root, preventing dashboard health
  refreshes from multiplying hardened Git subprocesses.

## Security Qualification

- Keeps governed compile and explain tools absent from MCP unless the operator
  delegates an exact contract ID and SHA-256 digest to a single-project process.
- Reconstructs stored context chunks before compilation and rejects count,
  ordering, content, or digest drift instead of trusting derived SQLite rows.
- Binds dashboard results to the exact project, task, budget, compiler, agent,
  and comparison inputs that produced them, discarding stale async responses.
- Treats unknown Git status as unavailable, never clean, for freshness and
  consequential-action governance.
- Hardens release checks against Windows archive traversal, untrusted Git
  resolution, mutable baselines, extended UNC paths, and unbounded privacy-scan
  enumeration.

The frozen pre-remediation Codex Security snapshot recorded eight findings. All
eight have focused regression coverage and are remediated in this candidate; the
historical report remains unchanged and explicitly identifies the older content
snapshot it assessed.

## Comparative Regression Evidence

The public benchmark now compares the real v0.6 pack builder with the real v0.8
compiler on one transparent synthetic continuation fixture at the same effective
input budget. The current local result recovers one of four explicit controls in
the legacy pack and four of four in the governed compiler, while increasing
control density per 1,000 estimated tokens. The fixture digest, raw counts,
deltas, and limitations are emitted on every run. This is synthetic regression
evidence, not an external agent-success study or superiority claim.

## Compatibility

- Aligns Python, CLI, dashboard package, binary-smoke, and development-console
  metadata on `0.8.0a1` / `v0.8.0-alpha`.
- Existing v1 task-contract digests remain stable when comparison variants are
  omitted.
- Existing context packs, retrieval, checkpoints, temporal truth, MCP tools, and
  project databases remain available.
- Schema migration is atomic, retryable, immutable after completion, and covered
  by rollback and collision tests.

Commit, push, hosted cross-platform CI, tag, release, website, and public
documentation remain separate owner-approval gates.
