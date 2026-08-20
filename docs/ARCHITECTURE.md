# Architecture

Rta-Smriti is a local Python application with a React operator surface. It has no hosted control plane.

```text
Repository / thread / memory
          |
          v
Fail-closed ingestion policy
  | parser registry
  | event-scoped content verification
  | incremental stat manifest
  | SHA-256 cache
          |
          v
SQLite project brain
  | sources + chunks
  | FTS5 indexes
  | optional local vectors
  | entities + evidence edges
  | durable memories + pramana
  | structured checkpoints + claim provenance
  | governance policies + decision receipts
  | workspace references + memory feedback
          |
          +--> CLI / stdio MCP
          +--> loopback-only dashboard
          +--> focused context pack
          +--> selective bundle / authenticated snapshot
```

Codex JSONL sessions enter through a separate continuity adapter. It reads only sessions whose declared working directory is inside the selected canonical project root, persists byte cursors, preserves incomplete final records for the next cycle, redacts common credential shapes, and bounds oversized tool output before writing append-only events. Initial capture is bounded by session age and a recent byte tail; a provenance-bearing `history_truncated` event exposes omitted history, after which every complete appended record is captured.

## Storage

Each brain is one SQLite database. Connections reject symbolic, reparse, and hard-linked database files; apply owner-only POSIX modes where available; disable SQLite trusted schema; and use WAL journaling, normal synchronous durability, foreign keys, and a bounded busy timeout. Concurrent agents can read while crash-safe writes remain transactional. Project settings, portable repository identity, canonical root binding, manifests, file hashes, chunks, FTS records, optional embedding vectors, memories, claim provenance, versioned checkpoints, governance records, workspace references, entities, edges, evidence, and recall receipts remain local.

## Ingestion

The walker rejects links, non-regular files, ignored folders, traversal overages, total-size overages, and sources above the project's configured cap. A stat manifest skips unchanged repositories. Filesystem events bypass metadata shortcuts and bind a content-hash read to the repository root, even when size and modification time were restored. Only changed files are parsed, chunked, indexed, and embedded. `watch-repo` runs this incremental path in the foreground. The `watcher` lifecycle command runs it in a detached per-project worker, using optional filesystem events when `watchdog` is installed and portable polling otherwise. Polling workers force a full content verification at least every five minutes so same-stat changes cannot remain indefinitely invisible.

Deep freshness uses SHA-256 values cached by project, absolute source path, size, and nanosecond modification time. `ingest-repo --force` bypasses the manifest and metadata shortcuts for an uncached re-read.

Freshness output is anomaly-first: changed, missing, added, and blocked files are returned up to a bounded detail limit, while fresh-file rows are summarized unless explicitly requested.

## Project Identity

A named project is bound to a portable repository identity plus one resolved canonical root. Git repositories use stable repository history identity; non-Git folders receive a local marker under the ignored `.rta-smriti` directory. If a legacy Git-local marker is present after a project was already bound to a stable Git history identity, the binder recomputes the first-commit identity and accepts only that exact match. A moved checkout relocates automatically only when its identity matches and the old root is gone. A live alternate root still requires explicit rebind, and a different identity is always rejected. Routine context generation reads Git HEAD and refs natively; the dashboard alone runs the heavier dirty-worktree scan.

## Parser Boundary

`ParserRegistry` ships with:

- automatic parsing, using Tree-sitter when installed and supported, then deterministic regex fallback
- deterministic regex parsing, always available
- an optional `tree-sitter-language-pack` adapter
- an explicit local command adapter for LSP-derived symbols and imports
- Python entry points in the `rta_smriti.parsers` group

Unavailable or failed optional parsers fall back to regex and emit warnings in the ingestion receipt.

## Retrieval

FTS5 BM25 remains available on every project. The recommended bootstrap path enables hybrid ranking that combines lexical rank with local cosine similarity through the dependency-free feature-hash provider. Operators can select lexical-only retrieval or a Sentence Transformers adapter, which loads only when separately installed and selected.

Context packs enforce a caller-selected token budget. Checkpoints and high-ranked `pratyaksha` evidence are considered first; lower-priority memories and chunks are omitted when needed, and the pack states when pruning occurred. Optional `tiktoken` provides model tokenization while the dependency-free path uses a conservative deterministic estimate.

Retrieval diagnostics report the active mode, provider, embedding coverage, parser fallbacks, freshness, elapsed time, rank components, source hashes, normalized query terms, and per-result selection reasons. The public benchmark ships as package data and compares no-memory, lexical, and dependency-free hash-hybrid modes on a synthetic corpus. An explicit flag can add an available local Sentence Transformers model; otherwise the result records that optional semantic evidence was not requested. Its results are regression evidence, not a claim of market superiority.

## Governance

Typed policies describe constraints, failed approaches, fragile paths, required checks, and prohibited repetition. Preflight evaluation is deterministic and scope-aware. Only high-trust, verified, hash-backed policy evidence can independently block; weaker records are warnings. Optional operational context adds transient warnings for consequential actions when checkpoint readiness, continuity capture, Git dirty state, canonical root, or index freshness is not green. Every evaluation emits a short-lived receipt bound to the action and current policy digest. Owner overrides record actor, reason, and matched policy evidence. Agent MCP tools cannot mutate policy, attest required checks, or override a block.

## Graph Intelligence

Ingestion records files, symbols, imports, approximate calls, tests, configuration, memories, and evidence links. Bounded graph queries traverse dependencies, dependents, impact, evidence, or relevance to depth four and at most 500 nodes. Each query returns its enforced relation filter: dependency views use calls/imports, impact adds containment/tests, evidence follows containment/tests/memory mentions, and relevance follows memory mentions only. Confidence labels make approximate edges distinguishable from direct source relationships.

## Workspaces And Portability

A workspace is metadata owned by one brain database that references explicitly selected projects in independent local brain databases. Search requires each member to remain an existing, unlinked regular file, opens external databases in SQLite query-only mode, writes no recall receipts, and returns grouped results; project identity and storage remain isolated.

Selective bundles contain only chosen memories, checkpoints, and policies. Source code is excluded. Export redacts home paths and common credential patterns by default and attaches a SHA-256 content digest for integrity, not authentication. Preview mode reports contents, warnings, conflicts, and the digest without mutating disk or a destination brain. Import verifies the envelope, validates bounded schemas, and stages every change in an in-memory SQLite copy before one atomic commit under an explicit rename, merge, or fail conflict strategy. Because bundles are unsigned, imported memories are downgraded to unverified `smriti`; imported checkpoints and policies are quarantined for owner review rather than gaining authority. Bundle inputs are limited to 25 MB and read through a stable descriptor. Private bundle and snapshot writes reject linked paths and use restrictive atomic writes. Authenticated snapshots use a consistent SQLite backup plus HMAC-SHA256 and a separate local shared key. Verification authenticates the manifest before decoding, caps the database at 64 MiB and legacy envelopes at 16 MiB, and uses bounded reads. Snapshots detect tampering but do not encrypt the database or provide public-key identity.

## Memory Lifecycle

Helpful, neutral, and harmful outcomes are explicit operator feedback. Conservative decay can reduce confidence only for old, unverified `anumana` and `kalpana` records that have not been reinforced. Verified claims and `pratyaksha` or `sabda` evidence are protected.

## Agent Concurrency

The stdio MCP server is bound to one project and exposes only read tools by default. Memory writes, repository ingestion, and thread ingestion require separate startup capabilities; repository ingestion always uses the registered canonical root, short-circuits when the current index is already fresh, and thread ingestion requires explicit allowed roots plus descriptor-bound reads. Agent-authored memory is downgraded to unverified `anumana` and cannot self-assert source authority. Blocking SQLite, hashing, parsing, and embedding work moves to worker threads with bounded request count, bytes, JSON nesting, and concurrency. Mutation visibility is ordered, memory batches are atomic, and checkpoints use optimistic versions under a SQLite write transaction so stale agents cannot silently overwrite newer continuation state.

## Background Sync

Managed watchers are explicit user processes, not privileged services. A random launch capability binds each worker to an unlinked lock file. State, heartbeat, counters, stop requests, and logs live beside the selected brain under `.rta-smriti-daemons`. Control files reject symbolic and hard links, state writes are atomic, repository events are coalesced, and every indexing cycle uses a fresh SQLite connection and one rollback-safe transaction. The dashboard never accepts a client-supplied watch root; it reads the canonical root already bound to the selected project.

The console has the same explicit start/open/status/restart/stop lifecycle and stores its capability token in a restricted local control file. Optional login startup writes only an owner-requested user-level registration and can be inspected or removed by the same CLI. The foreground `dashboard` command remains available for diagnostics.

The continuity daemon uses the same managed-process safety model but never changes repository files. It captures a bounded number of pending sessions and events per cycle so stop requests remain responsive. Automatic checkpoints are created only after the newest matching transcript is fully consumed and a terminal, inactivity, or service-shutdown trigger occurs. They carry `source=continuity-daemon`, keep `verified_evidence` empty, and explicitly require operator verification. Manual checkpoints remain separately identifiable.

On POSIX systems, brain databases, WAL/SHM sidecars, daemon state, and logs are restricted to the owning user (`0600`), while daemon control directories use `0700`. Rta-Smriti rejects linked database/control artifacts and files owned by another user. These controls do not isolate mutually untrusted processes running under the same operating-system account; use a dedicated OS account or machine boundary for that threat model.

## Multi-Project MCP Gateway

One stdio MCP process can receive a brain directory instead of one database. Each tool call must name a project. The gateway scans only unlinked SQLite files in that directory and opens the call against exactly one matching project database. Missing and duplicate project names fail closed, preventing accidental cross-project recall while avoiding six copies of the same MCP tool set.

## Distribution

`pyproject.toml` console scripts are the primary source installation path. Static dashboard assets and the public benchmark corpus are included as package data and exercised from a clean wheel. A versioned PyInstaller specification and three-operating-system GitHub workflow build standalone Windows, macOS, and Linux artifacts without making PyInstaller a runtime dependency.

## Trust Boundary

The HTTP console binds only to loopback, requires a per-launch capability token, validates local origins, and confines database paths to its configured brain directory. Retrieved repository text is evidence, not executable instruction. Blocked or uninspectable sources keep freshness fail-closed.
