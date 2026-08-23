# Release Verification

This page records the evidence boundary for `v0.9.0-alpha`. It separates
source qualification, hosted compatibility, tag-generated artifacts, and
post-publication download checks so a passing test is never presented as proof
of a different release gate.

## Publication State

- Source version: `0.9.0-alpha` (`0.9.0a1` in Python package metadata)
- Published branch: `main`
- Verified v0.9 source merge: `4f40aff1953d73080aff14dbb7e98034d76af735`
- Formal tag: `v0.9.0-alpha` (created only after the publication metadata PR passes)
- Formal release: [Rta-Smriti Brain v0.9.0-alpha](https://github.com/sulabhdubey/rta-smriti-brain/releases/tag/v0.9.0-alpha)
- Release classification: alpha prerelease

The release workflow produces Windows x64, Linux x64, and macOS standalone
binaries, a universal wheel, CycloneDX SBOMs, and a combined SHA-256 manifest.
Artifact acceptance additionally requires redownloading the public files and
matching them to `SHA256SUMS.txt`.

## v0.9 Scope

The v0.9 line combines four governed foundations:

1. Canonical project identity prevents silent switching between duplicate roots,
   clones, or worktrees.
2. The event-sourced bitemporal truth kernel records what was asserted, when it
   was valid, when it was learned, supporting evidence, contradictions,
   validation, and abstention.
3. The governed context compiler selects agent-specific context under immutable
   task contracts, privacy grants, trust ordering, and hard token budgets.
4. Universal Capture normalizes opt-in agent events through a private bounded
   spool and one per-brain daemon into a redacted hash-chained journal.

Captured content remains untrusted evidence. Replay never executes captured
actions. Read-only MCP responses are project-scoped and path-free by default;
process control, retention, export, redaction, and deletion remain separate
capabilities.

## Verified Source Evidence

| Gate | Result |
| --- | --- |
| Local Python regression | 760 passed, 23 explicit optional-dependency or privilege skips, 649 subtests |
| Focused console, onboarding, and spool suite | 84 passed, 6 skipped |
| Managed console fallback identity tests | 2 passed |
| Dashboard unit and production build | Passed |
| Rendered operator journey | Passed, including Universal Capture export integrity and privacy assertions |
| Installed package lifecycle | Upgrade and uninstall from `0.8.0a1` to `0.9.0a1` passed |
| Windows native smoke | CLI, SQLite/FTS, MCP, benchmark, Tree-sitter, Universal Capture, encrypted snapshot, Ed25519, sync, and console passed |
| Capture performance | 10,000 events at 170.445 events/s; replay page p99 43.071 ms; bounded backpressure verified |
| Feature PR hosted CI | [Run 32635867425](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32635867425) passed Windows, macOS, and Ubuntu |
| Post-merge hosted CI | [Run 32636448594](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32636448594) passed all five jobs |
| GitHub Pages deployment | Post-merge deployment passed before the release metadata refresh |

The publication metadata and website changes are rerun through the same hosted
matrix before tagging. The final release record is updated with the exact tag
commit, tag workflow, asset manifest, and post-download checks.

## Security And Privacy Evidence

The v0.9 source candidate passed the repository privacy scanner, Gitleaks history
and working-tree scans, actionlint, npm audit, Python dependency audit, wheel
inspection, checksum verification, package-content checks, and focused
security-control tests.

A later Codex Deep Security Scan coordinator attempt is **not** counted as
coverage: both workers were blocked before workspace inventory or source review,
and completion rejected a non-UUID scan identifier. It produced no usable sealed
report and found no file-level issue only because it inspected no files. The
release record does not convert that failed scan into a clean result.

Release publication excludes local brain databases, spools, transcripts,
capability tokens, keys, private project content, raw diagnostics, generated
context packs, operator paths, and the private local v0.9 design/implementation
documents. Public screenshots and media use synthetic data.

## Reproduction

Run from the repository root:

```powershell
npm run test:unit
npm run build
npm run build:launch
npm run test:launch
python -m pytest -q
python -m compileall -q rta_brain tests scripts
python scripts/build_installed_smoke.py
python scripts/privacy_scan.py --root .
python scripts/performance_probe.py --profiles 100 1000 --assert-bounds
python rta-brain.py publish-readiness --json
actionlint
gitleaks git --redact --no-banner --verbose .
git diff --check
```

The native release workflow additionally audits dependencies, generates SBOMs,
builds and smoke-tests each operating-system artifact, packages versioned files,
privacy-scans the staged bundle, and uploads it for release assembly.

## Residual Boundaries

- Managed workers are user-level local processes; login startup is explicit.
- Same-user malware or administrator/root access can read operator-owned data.
- Secret detection is defense in depth, not proof against every unknown format.
- Vendor event formats and optional local adapters can change.
- Filesystem deletion cannot guarantee erasure from SSD wear leveling or copies.
- Call edges and unsupported-language parsing remain bounded impact hints.
- The synthetic benchmark is reproducibility evidence, not external superiority
  proof.

See [Publishing Privacy](PUBLISHING_PRIVACY.md), the
[v0.9 threat model](security/v0.9-capture-threat-model.md), and
[Security Policy](../SECURITY.md).

## Historical Evidence

- [v0.6 release notes](RELEASE_NOTES_v0.6.0-alpha.md)
- [v0.4 release notes](RELEASE_NOTES_v0.4.0-alpha.md)
- [v0.3 launch snapshot](archive/LAUNCH_READINESS_v0.3.0-alpha.md)

Historical records describe their own frozen versions and must not be interpreted
as the current v0.9 release state.
