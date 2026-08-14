# Security Policy

Rta-Smriti Brain is local-first and stores data in SQLite files controlled by the user.

## Current Security Boundary

- No outbound network calls by default.
- The dashboard serves a local HTTP console on `127.0.0.1`.
- No cloud sync.
- No API keys required.
- No background daemon.
- MCP server reads and writes only the configured SQLite database and paths supplied by tool calls.

## Sensitive Data

Do not store secrets, bearer tokens, cookies, SSH keys, private API keys, customer data, or credentials. The V1/V2 implementation does not perform automated secret scanning or redaction.

## Safe Usage

- Use one database per project unless you explicitly want shared memory.
- Treat `smriti` and `anumana` memories as memory-derived, not confirmed-current.
- Re-run `stale-check` and re-read changed files before relying on old repo context.
- Keep brain databases out of public repositories.

## Reporting

For public use, report vulnerabilities through GitHub Security Advisories when the repository is published.
