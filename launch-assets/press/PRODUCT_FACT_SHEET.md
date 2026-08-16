# Rta-Smriti Brain Fact Sheet

**Category:** Open-source developer tool, local AI project memory

**Current release:** [`v0.4.0-alpha`](https://github.com/sulabhdubey/rta-smriti-brain/releases/tag/v0.4.0-alpha)

**Release state:** Published as a GitHub prerelease on August 16, 2026, with SHA-256 checksums, a wheel, and standalone Windows, Linux, and macOS artifacts.

**License:** MIT

**Runtime:** Python 3.11+, SQLite/FTS5, zero Python runtime dependencies

**Interfaces:** CLI, stdio MCP server, packaged React operator console

**Problem:** AI coding sessions repeatedly lose repository context, durable decisions, release rules, and prior-session knowledge.

**Solution:** One private brain per project that indexes repository structure, stores durable memory, ingests handoffs, classifies evidence, and generates bounded context packs for a concrete task.

**Privacy:** Local SQLite storage, loopback-only console, no account, no telemetry, no hosted database.

**Validation:** See [`docs/RELEASE_VERIFICATION.md`](../../docs/RELEASE_VERIFICATION.md) for current, reproducible checks and [`docs/PUBLIC_BENCHMARK.md`](../../docs/PUBLIC_BENCHMARK.md) for the privacy-safe synthetic benchmark. Historical test counts and private-project scale claims are intentionally excluded from this fact sheet.

**Primary differentiator:** Repository evidence, durable human memory, session handoffs, evidence class, freshness, and agent-ready context are combined in one inspectable local layer.
