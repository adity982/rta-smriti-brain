# Rta-Smriti v0.7 Temporal Truth Kernel Design

Status: Owner-approved for local implementation on 2026-08-22. Commit, push,
merge, release, deployment, and publication remain separate approval gates.

Baseline: `feature/v0.7-temporal-truth` at
`3af3c617a1565e6ed04d9acdba7a0a23b6adae05`.

## Purpose

Rta-Smriti must answer four different questions without collapsing them:

1. What was claimed to be true about the project?
2. When was that claim intended to be valid?
3. When did Rta-Smriti record or learn the claim?
4. What evidence, contradiction, correction, or validation changed its standing?

The temporal truth kernel adds an immutable event ledger and deterministic
bitemporal projections for consequential project knowledge. It does not turn
Rta-Smriti into an execution engine, general event bus, or external database
service.

## Design Choice

Use selective event sourcing for truth-bearing memory only. Repository indexes,
FTS tables, embeddings, settings, caches, process state, and dashboard layout
remain ordinary rebuildable or operational tables.

Rejected alternatives:

- Adding timestamps to mutable memories cannot reconstruct prior belief or
  represent competing claims without destructive updates.
- Requiring a separate temporal database adds a service dependency and weakens
  the offline, one-command product boundary.
- Event-sourcing every table would increase complexity without improving
  continuity or evidence quality.

## Invariants

1. Truth events are inserted, never updated or deleted through supported APIs.
2. Corrections, retractions, expiry, and refutation are new events.
3. Event sequence is the authoritative recorded order. Wall-clock time is
   descriptive and may be skewed.
4. Valid-time and recorded-time intervals are half-open: `[from, to)`.
5. Current-state and historical projections are fully rebuildable from events.
6. Replaying the same event set with the same projection version produces the
   same canonical projection digest.
7. Duplicate idempotency keys return the original event and do not create a
   second state transition.
8. A stale expected stream version fails before any event or projection write.
9. Unknown event schemas halt replay fail-closed; stored events are never
   rewritten by migrations or upcasters.
10. Historical and contradictory claims remain inspectable.
11. A Git commit query succeeds only when an explicit observed anchor exists.
12. Retrieved event payloads are untrusted evidence and never executable
    instructions.
13. Sensitive or restricted payloads are not embedded in immutable envelopes by
    default.
14. Hash chaining detects accidental or unsupported mutation. It is not claimed
    to resist a same-user attacker who can rewrite the SQLite file and schema.

## Vocabulary

- **Event:** immutable record of intent or observation.
- **Claim:** one subject-predicate-object assertion with a stable claim ID.
- **Valid time:** when the claim applies in the project or external domain.
- **Recorded time:** when the brain accepted the event, ordered by project
  sequence.
- **Projection:** disposable query model rebuilt from the ledger.
- **Anchor:** verified association between an event sequence and repository,
  checkout, branch, commit, and optional dirty digest.
- **Evidence:** provenance-bearing support or opposition to a claim.
- **Abstention:** explicit record that available evidence cannot support an
  answer.

## Event Envelope

`truth_events` is the local source of authority.

| Field | Purpose |
| --- | --- |
| `id` | SQLite row identity |
| `project_id` | Canonically bound project |
| `project_sequence` | Monotonic order within one project |
| `event_id` | Portable opaque identifier |
| `stream_id` | Aggregate stream such as `claim:<id>` |
| `stream_version` | Optimistic concurrency version |
| `event_type` | Intent-bearing event name |
| `event_schema` | Immutable payload schema version |
| `idempotency_key` | Caller retry identity |
| `payload_json` | Bounded canonical JSON or safe content reference |
| `payload_sha256` | Digest of canonical payload bytes |
| `previous_event_hash` | Prior project event hash |
| `event_hash` | Digest of envelope and previous hash |
| `actor_type`, `actor_id` | Operator, agent, daemon, migration, or adapter |
| `source` | CLI, MCP, dashboard, migration, validator, or adapter |
| `verification_status` | Unverified, verified, failed, or stale |
| repository context | Repository identity, checkout identity, ref, commit, dirty digest |
| `occurred_at` | Optional source-observed time |
| `recorded_at` | Brain-generated UTC time |
| `privacy_class` | Public, internal, sensitive, or restricted |

Constraints:

- Unique `(project_id, project_sequence)`.
- Unique `(project_id, stream_id, stream_version)`.
- Unique `(project_id, idempotency_key)`.
- Payload maximum 256 KiB and bounded JSON depth, strings, and collections.
- Project deletion is restricted while truth events exist.
- Persistent `BEFORE UPDATE` and `BEFORE DELETE` triggers abort event mutation.

All appends run inside `BEGIN IMMEDIATE`. The transaction verifies canonical
binding, acquires the single writer, checks the expected stream version,
allocates the project sequence, verifies the previous hash, inserts the event,
updates projections, and commits atomically.

## Event Types

The first stable event schema supports:

- `claim_asserted.v1`
- `claim_state_changed.v1`
- `claim_related.v1`
- `evidence_attached.v1`
- `abstention_recorded.v1`
- `validator_defined.v1`
- `validator_evaluated.v1`
- `repository_anchor_observed.v1`
- `legacy_memory_registered.v1`
- `projection_rebuilt.v1` is diagnostic metadata outside the authoritative
  claim streams and cannot alter truth.

Event names describe intent. Generic `row_updated` events are forbidden.

## Bitemporal Projection

`truth_claim_versions` is a rebuildable projection. Each row contains:

- stable `claim_id`;
- canonical subject key and display subject;
- predicate and canonical JSON object;
- polarity: `for`, `against`, or `unknown`;
- epistemic state and reason;
- authority class, confidence, and verification status;
- valid-time interval;
- recorded project-sequence interval;
- event IDs that opened and closed the projection row;
- repository anchor and provenance references;
- revalidation and expiry times;
- privacy class and sharing policy;
- optional legacy memory ID.

Recorded intervals use project sequence, not timestamps. Time-based queries
first resolve a deterministic sequence boundary. When multiple events share a
timestamp, their sequence remains unambiguous.

Queries:

- current truth at an explicit evaluation time;
- valid at time V, as recorded at sequence R;
- valid at V, as believed at explicit Git anchor C;
- complete claim history;
- truth diff between two sequences, times, commits, branches, or checkpoints;
- unresolved contradiction branches;
- expired, stale, disputed, or unsupported knowledge.

An absent commit anchor returns `abstain` rather than guessing the nearest
repository state.

## Epistemic State Machine

Supported states:

`hypothesis`, `observed`, `corroborated`, `accepted`, `disputed`, `stale`,
`refuted`, `superseded`, and `retracted`.

Rules:

- Agents may propose hypotheses or observations but cannot self-promote to
  accepted.
- `accepted` requires an explicit operator event or an approved deterministic
  policy with verified evidence.
- Contradictory active claims become disputed branches; neither is silently
  chosen.
- `superseded` means a newer applicable claim replaced a claim, not that the
  older claim was false.
- `refuted` requires negative evidence or a failed validator whose policy
  explicitly refutes the claim.
- Expired claims are effectively stale at query time even before a daemon emits
  a persistent state-change event.
- Retraction records withdrawal without erasing the claim or its evidence.

Every state transition is validated against an explicit transition table.
Invalid transitions fail without appending an event.

## Relations, Contradictions, and Negative Evidence

`truth_relations` is a rebuildable projection of relation events:

- `supports`
- `contradicts`
- `supersedes`
- `retracts`
- `refutes`
- `derived_from`
- `alternate_of`
- `specialization_of`

Automatic contradiction detection may propose a relation at low authority. It
must not resolve a branch. Negative evidence includes its observation method,
scope, limits, source hash, and actor. Absence is not negative evidence unless
the observation protocol establishes that absence is meaningful.

Abstention records the query scope, missing evidence, unresolved conflicts, and
the minimum revalidation action. It is not a synthetic claim.

## Proof-Carrying Evidence

`truth_evidence` projects evidence events and stores:

- source identifier or URI;
- content-addressed source or bounded excerpt hash;
- repository and checkout identity;
- command, tool, test, or observation;
- actor and agent/model identity when supplied;
- valid, recorded, and verification time;
- authority, confidence, uncertainty, and polarity;
- reproducibility recipe and validator ID;
- privacy classification and sharing policy;
- supporting, weakening, or refuting relation.

W3C PROV concepts map as follows:

- claims and artifacts are entities;
- commands, tests, and observations are activities;
- operators, agents, and adapters are agents;
- revisions, derivations, invalidations, alternates, and specializations retain
  their standard semantic direction.

## Executable Validators

Validator definitions are data, not commands. A registry maps known validator
types to bounded implementations:

- `file_exists`
- `file_sha256`
- `json_pointer_equals`
- `sqlite_integrity`
- `git_head_equals`
- `git_clean_state`
- `command_exit` only with an explicit operator capability, argv arrays, no
  shell, trusted executable policy, timeout, output cap, and canonical cwd.
- external status adapters only when explicitly configured, with `unavailable`
  distinct from pass or fail.

Untrusted repository content, transcript text, imported bundles, and agent MCP
calls cannot activate `command_exit` or install validator adapters.

Validator results append events. A failed result disputes, stales, or refutes a
claim according to the validator policy and exposes affected claims, context
packs, checkpoints, and readiness. Validators never delete evidence.

## Replay and Projection Integrity

`truth_projection_state` records projection name, schema version, last event
sequence, event-chain hash, projection digest, and rebuild time.

Rebuild procedure:

1. Verify project binding and event chain.
2. Create projection tables in a private transaction scope.
3. Replay events in project-sequence order through versioned pure handlers.
4. Halt on gaps, hash mismatch, unknown event type/schema, invalid transition,
   or malformed bounded payload.
5. Compute a canonical projection digest.
6. Atomically replace existing projection rows and metadata.
7. Compare the rebuilt digest with the live projection digest.

Upcasters transform old event payloads in memory only. Stored event bytes and
hashes remain unchanged. Projection snapshots are optional performance caches,
never authority.

## Migration from Schema 7

Schema 8 migration is atomic and backward-aware:

1. Acquire the canonical binding gate and `BEGIN IMMEDIATE`.
2. Create ledger, projections, indexes, triggers, and migration metadata.
3. Register each existing memory through one idempotent
   `legacy_memory_registered.v1` event.
4. Preserve the original memory ID, creation time, status, pramana, confidence,
   provenance, and content hash.
5. Set event `recorded_at` to migration time. Never fabricate historical
   transaction time from the legacy memory creation time.
6. Map unverified legacy memory to hypothesis, verified direct/trusted evidence
   to observed or corroborated, failed evidence to refuted, stale to stale,
   contradicted to disputed, and superseded to superseded. Migration never
   assigns accepted.
7. Append a bounded migration receipt with counts and digest.
8. Commit only after replay reproduces the migration projection digest.

Existing memory, FTS, and provenance tables remain available for v0.6 API
compatibility. During v0.7, new temporal memory writes append an event and update
the compatibility projection in the same transaction. A migration failure or
process crash leaves schema 7 data unchanged.

Backup and rollback tests must prove restoration before schema publication.

## Interfaces

### Python

`rta_brain.temporal` owns event validation, append, replay, temporal queries,
relations, evidence, validators, and deterministic digests. It depends on the
existing canonical binding and SQLite connection layers but not on CLI, MCP, or
dashboard code.

### CLI

One `truth` command group provides:

- `assert`, `state`, `relate`, `evidence`, and `abstain`;
- `current`, `as-of`, `history`, and `diff`;
- `validator add`, `validator run`, and `validator history`;
- `ledger verify`, `projection rebuild`, and `projection compare`.

JSON output is stable and bounded. Mutations require the exact project binding
and use expected stream versions and idempotency keys.

### MCP

Read tools are available by default:

- `brain_truth_current`
- `brain_truth_as_of`
- `brain_truth_history`
- `brain_truth_diff`
- `brain_truth_explain`

Truth writes require a separate `--allow-truth-write` capability. Validator
execution requires `--allow-validator-run` in addition to validator policy.
Agent writes are capped at hypothesis/observed authority.

### Dashboard

Add operator surfaces progressively:

- timeline and replay controls;
- truth-diff view;
- contradiction queue;
- claim and evidence inspector;
- validator health and blast radius;
- explicit states for current, historical, stale, disputed, unavailable, and
  abstained results.

Every control must call a real API or be disabled with a reason. Existing Graph,
Canvas, Bases, Files, Memory, Evidence, Continue, Packs, Settings, and release
surfaces remain coherent.

## Retrieval and Readiness Integration

Search and context packs add temporal candidates without hiding legacy results.
Ranking considers authority, verification, valid-time applicability, recorded
time, expiry, contradiction, provenance, and task relevance. Disputed or refuted
claims may be returned for warning or historical analysis but are never silently
presented as current accepted truth.

Operational readiness distinguishes:

- healthy database;
- intact event ledger;
- current projection;
- unresolved high-impact contradiction;
- failed or expired critical validator;
- missing checkpoint or continuity capture;
- wrong canonical root or Git anchor.

## Security and Privacy Model

Assets include project truth, event integrity, provenance, local brain contents,
validator authority, and canonical identity.

Primary boundaries:

- untrusted repository/transcript/import content to event validation;
- agent MCP host to capability-gated mutation;
- dashboard browser to loopback token API;
- validator definitions to trusted local execution;
- concurrent daemon, MCP, CLI, and dashboard writers to SQLite;
- export/snapshot boundary to public or shared artifacts.

Threat controls:

- canonical-root and checkout revalidation inside the write transaction;
- bounded canonical JSON and strict event schemas;
- parameterized SQL and no unsafe deserialization;
- no shell execution and no agent-enabled command validators;
- append-blocking triggers and event-chain verification;
- privacy class checks before inline storage, retrieval, export, or diagnostics;
- stable descriptor reads for evidence files;
- explicit retention and deletion design for payload references;
- resource bounds for replay, graph expansion, validator time, and output.

The local database remains controlled by the operating-system user. v0.7 does
not claim protection from that user intentionally rewriting the database and
schema. Signed snapshots provide stronger offline tamper evidence at explicit
checkpoints.

## Performance Budgets

Measured on the project test machine with warm filesystem cache unless stated:

- append p95 under 25 ms at 100,000 project events;
- current-claim query p95 under 50 ms;
- bitemporal as-of query p95 under 100 ms;
- truth diff of 1,000 affected claims under 500 ms;
- deterministic replay of 100,000 small events under 15 seconds;
- idle temporal maintenance adds no persistent worker and no measurable daemon
  wakeups beyond existing continuity/sync intervals;
- average synthetic event storage under 4 KiB before source payload references;
- all APIs enforce result and payload bounds.

Performance evidence reports dataset, cold/warm state, repetitions, p50, p95,
p99, variance, peak memory, and database growth. A budget miss is reported, not
hidden by reducing correctness.

## Test Strategy

### Unit and property tests

- event schema bounds and canonical serialization;
- legal and illegal epistemic transitions;
- interval overlap and half-open boundary behavior;
- deterministic hash and projection digest;
- contradiction and abstention semantics;
- validator policy mapping;
- randomized replay produces the same projection as incremental application.

### Transaction and resilience tests

- duplicate idempotency key;
- stale expected stream version;
- concurrent append allocation;
- direct event UPDATE and DELETE rejection;
- process interruption before event insert, after event insert, and before
  projection commit;
- database lock, disk-full simulation, malformed WAL recovery, and stale lease;
- migration rollback, restart, repeated migration, backup, and downgrade path;
- unknown event schema and event-chain corruption halt replay.

### Temporal acceptance scenarios

- retroactive correction preserves the previous recorded belief;
- valid-at V / recorded-at R returns the correct branch;
- same-timestamp events resolve by sequence;
- branch and commit queries require explicit anchors;
- competing claims remain visible and unresolved;
- expiry changes effective state without rewriting history;
- validator failure propagates to readiness and context output;
- projection deletion and rebuild produce an identical digest.

### Surface parity

- Python, CLI JSON, MCP, dashboard, installed wheel, and native executable return
  equivalent bounded semantics;
- Windows, macOS, and Linux path, clock, locking, and packaging behavior;
- Playwright operator journeys for timeline, diff, contradiction, validator,
  keyboard, accessibility, responsive, error, and recovery states;
- privacy scan, Gitleaks, actionlint, dependency audit, SBOM, package/binary
  inspection, security diff scan, threat-model review, and adversarial tests.

## Implementation Slices

1. Ledger schema, event append, immutability, idempotency, optimistic concurrency,
   and chain verification.
2. Claim projections, state machine, deterministic replay, migration, and
   bitemporal queries.
3. Relations, contradiction branches, negative evidence, abstention, expiry,
   and Git anchors.
4. Validator registry, result events, blast radius, readiness, and retrieval.
5. CLI and MCP capability boundaries.
6. Dashboard timeline, truth diff, contradictions, evidence, and validator UX.
7. Performance, resilience, security, privacy, packaging, cross-platform, and
   human-operator qualification.

Each production slice begins with a failing test, ends with focused and broader
green verification, and updates the structured Rta-Smriti checkpoint. No slice
is committed or published without a new owner approval for the exact candidate.

## Release Acceptance

v0.7 is ready for owner review only when:

- current projections rebuild deterministically from immutable events;
- historical valid-time and recorded-time queries are correct;
- corrections and contradictions preserve inspectable history;
- failed validators demote claims and propagate operational risk;
- migration and rollback preserve every legacy record;
- CLI, MCP, dashboard, installed package, and native artifact agree;
- operator, accessibility, resilience, performance, security, privacy, and
  cross-platform gates pass with reproducible evidence;
- no private data appears in source, diff, packages, binaries, screenshots,
  website assets, reports, SBOM, or release materials;
- the exact uncommitted candidate is presented for separate owner approval.
