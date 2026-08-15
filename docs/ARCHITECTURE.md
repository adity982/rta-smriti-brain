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

Each brain is one SQLite database. Project settings, canonical root binding, manifests, file hashes, chunks, FTS records, optional embedding vectors, memories, claim provenance, structured checkpoints, entities, edges, evidence, and recall receipts remain local.

## Ingestion

The walker rejects links, non-regular files, ignored folders, traversal overages, total-size overages, and sources above the project's configured cap. A stat manifest skips unchanged repositories. Changed files alone are parsed, chunked, indexed, and embedded. `watch-repo` polls this incremental path in the foreground.

Deep freshness uses SHA-256 values cached by project, absolute source path, size, and nanosecond modification time. `ingest-repo --force` bypasses the manifest and metadata shortcuts for an uncached re-read.

Freshness output is anomaly-first: changed, missing, added, and blocked files are returned up to a bounded detail limit, while fresh-file rows are summarized unless explicitly requested.

## Project Identity

A named project is bound to one resolved canonical root. Ingestion refuses a different root unless the operator explicitly uses the root-rebind control. The console also compares brains in its configured directory and warns when the same project name is bound to multiple roots. Git state is read through a trusted Git installation and reports repository root, branch, HEAD, and dirty-file count.

## Parser Boundary

`ParserRegistry` ships with:

- deterministic regex parsing, always available and the default
- an optional `tree-sitter-language-pack` adapter
- an explicit local command adapter for LSP-derived symbols and imports
- Python entry points in the `rta_smriti.parsers` group

Unavailable or failed optional parsers fall back to regex and emit warnings in the ingestion receipt.

## Retrieval

FTS5 BM25 remains available on every project. The recommended bootstrap path enables hybrid ranking that combines lexical rank with local cosine similarity through the dependency-free feature-hash provider. Operators can select lexical-only retrieval or a Sentence Transformers adapter, which loads only when separately installed and selected.

## Trust Boundary

The HTTP console binds only to loopback, requires a per-launch capability token, validates local origins, and confines database paths to its configured brain directory. Retrieved repository text is evidence, not executable instruction. Blocked or uninspectable sources keep freshness fail-closed.
