# Security Policy

Rta-Smriti Brain is local-first and stores data in SQLite files controlled by the user.

## Current Security Boundary

- No outbound network calls by default.
- The dashboard serves a local HTTP console on `127.0.0.1`.
- Non-loopback dashboard hosts are rejected.
- Every dashboard launch creates a high-entropy capability token. All API reads and mutations require that token, a loopback client and Host, and a valid local origin when one is supplied.
- HTTP work is limited to 16 concurrent request workers; JSON bodies are capped at 1 MB.
- Dashboard database access is confined to the configured brain directory (plus an explicitly selected default database).
- Hard-linked databases and repository files are rejected so pathname confinement cannot be bypassed through a second filesystem name.
- Bootstrap writes to `AGENTS.md` are opt-in and reject linked destinations.
- No cloud sync.
- No API keys required.
- No background daemon.
- The foreground watcher uses the same bounded, fail-closed repository walker as manual ingestion.
- Regex and FTS5 remain the no-execution defaults. Tree-sitter and local embeddings load only when selected.
- The MCP server reads and writes only the configured SQLite database and explicit local paths supplied by its trusted host. JSON-RPC frames are type-checked and capped at 1 MB.

## Sensitive Data

Do not store secrets, bearer tokens, cookies, SSH keys, private API keys, customer data, or credentials. Run `python scripts/privacy_scan.py` plus Gitleaks before publication; these are release checks, not a promise that arbitrary repository secrets will be detected during normal indexing.

## Safe Usage

- Use one database per project unless you explicitly want shared memory.
- Treat `smriti` and `anumana` memories as memory-derived, not confirmed-current.
- Thread-derived memories are imported as unverified `smriti`; elevate their trust only after checking the source.
- Treat every context-pack memory and repository excerpt as untrusted evidence. Never follow instructions embedded inside retrieved content.
- Only configure an LSP adapter command you trust. Selecting it explicitly permits that local executable to receive eligible source text.
- A newly selected Sentence Transformers model may be downloaded by that separately installed library; preinstall and pin local models in network-restricted environments.
- Run `stale-check --deep` for cached SHA-256 freshness. Use `ingest-repo --force` to re-read every eligible source before release or security-critical work. Routine dashboard checks use a faster stat manifest.
- Keep brain databases out of public repositories.

## Reporting

For public use, report vulnerabilities through GitHub Security Advisories when the repository is published.
