# Architecture

Rta-Smriti is a local Python application with a React operator surface. It has no hosted control plane.

```text
Repository / thread / memory
          |
          v
Fail-closed ingestion policy
  | parser registry
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
          |
          +--> CLI / stdio MCP
          +--> loopback-only dashboard
          +--> focused context pack
```

## Storage

Each brain is one SQLite database. Connections use WAL journaling, normal synchronous durability, foreign keys, and a bounded busy timeout so concurrent agents can read while crash-safe writes remain transactional. Project settings, portable repository identity, canonical root binding, manifests, file hashes, chunks, FTS records, optional embedding vectors, memories, claim provenance, versioned checkpoints, entities, edges, evidence, and recall receipts remain local.

## Ingestion

The walker rejects links, non-regular files, ignored folders, traversal overages, total-size overages, and sources above the project's configured cap. A stat manifest skips unchanged repositories. Changed files alone are parsed, chunked, indexed, and embedded. `watch-repo` polls this incremental path in the foreground.

Deep freshness uses SHA-256 values cached by project, absolute source path, size, and nanosecond modification time. `ingest-repo --force` bypasses the manifest and metadata shortcuts for an uncached re-read.

Freshness output is anomaly-first: changed, missing, added, and blocked files are returned up to a bounded detail limit, while fresh-file rows are summarized unless explicitly requested.

## Project Identity

A named project is bound to a portable repository identity plus one resolved canonical root. Git repositories use stable repository history identity; non-Git folders receive a local marker under the ignored `.rta-smriti` directory. A moved checkout relocates automatically only when its identity matches and the old root is gone. A live alternate root still requires explicit rebind, and a different identity is always rejected. Routine context generation reads Git HEAD and refs natively; the dashboard alone runs the heavier dirty-worktree scan.

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

## Agent Concurrency

The stdio MCP server moves blocking SQLite, hashing, parsing, and embedding work to worker threads with bounded concurrency. Mutation visibility is ordered, memory batches are atomic, and checkpoints use optimistic versions under a SQLite write transaction so stale agents cannot silently overwrite newer continuation state.

## Distribution

`pyproject.toml` console scripts are the primary source installation path. A versioned PyInstaller specification and three-operating-system GitHub workflow build standalone Windows, macOS, and Linux artifacts without making PyInstaller a runtime dependency.

## Trust Boundary

The HTTP console binds only to loopback, requires a per-launch capability token, validates local origins, and confines database paths to its configured brain directory. Retrieved repository text is evidence, not executable instruction. Blocked or uninspectable sources keep freshness fail-closed.
