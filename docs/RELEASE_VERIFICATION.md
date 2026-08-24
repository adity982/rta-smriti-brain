# Release Verification
## v0.9.1-alpha Candidate Verification

The v0.9.1 patch preserves the published v0.9 architecture and tightens the
operator surface around progressive loading, project isolation, lifecycle
status, and explicit multi-project MCP routing.

| Candidate gate | Result |
| --- | --- |
| Package metadata | `0.9.1a1` / `v0.9.1-alpha` |
| Full local Python regression | 768 passed; 23 explicit platform or optional-capability skips; 649 subtests passed |
| Dashboard unit tests | 5 passed |
| Progressive loading and project-switch isolation | 4 rendered adversarial journeys passed |
| Complete operator browser suite | 7 rendered journeys passed |
| Real local multi-project audit | Passed without browser errors, failed API responses, persistent loading states, false integrity alerts, or mobile overflow |
| Frozen Codex Security diff scans | 13 of 13 changed operator-readiness surfaces and 12 of 12 release/website code-bearing surfaces covered; zero findings |
| Privacy and secrets | Repository privacy scan and Gitleaks staged/history checks passed |
| Dependency integrity | npm audit found zero vulnerabilities; Python dependency check found no broken requirements |
| Patch integrity | `git diff --check` and actionlint passed |
| Hosted Windows/macOS/Linux CI | Pending exact committed candidate |
| Native binaries, wheel, SBOMs, and checksums | Pending tag workflow |
| GitHub Pages and anonymous download acceptance | Pending publication |

The real-project audit used private local brains only as operator fixtures.
Project names, roots, database contents, capability tokens, and local scan paths
are not included in this repository or its release evidence. Managed watchers,
continuity workers, and capture daemons remain explicit opt-in services; stopped
services are reported honestly and are not silently enabled by the dashboard.

The successful security result is a diff scan of the frozen v0.9.1 patch. It
does not replace the repository's existing threat model, privacy scanner,
Gitleaks coverage, dependency audits, hosted matrix, or artifact acceptance
gates. Hosted CI and release artifacts must pass before this candidate is
published.

## Published v0.9.0-alpha Baseline


This page records the evidence boundary for `v0.9.0-alpha`. It separates
source qualification, hosted compatibility, tag-generated artifacts, and
post-publication download checks so a passing test is never presented as proof
of a different release gate.

## Publication State

- Source version: `0.9.0-alpha` (`0.9.0a1` in Python package metadata)
- Published branch: `main`
- Universal Capture source merge: `4f40aff1953d73080aff14dbb7e98034d76af735`
- Final tag commit: `c8002a29c25d63fce5249ff60289966c9dbd3dc4`
- Formal tag: `v0.9.0-alpha`
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
| Local Python regression | 783 passed, 23 explicit optional-dependency or privilege skips, 649 subtests |
| Focused console, onboarding, and spool suite | 84 passed, 6 skipped |
| Managed console fallback identity tests | 2 passed |
| Dashboard unit and production build | Passed |
| Rendered operator journey | Passed, including Universal Capture export integrity and privacy assertions |
| Installed package lifecycle | Upgrade and uninstall from `0.8.0a1` to `0.9.0a1` passed |
| Windows native smoke | CLI, SQLite/FTS, MCP, benchmark, Tree-sitter, Universal Capture, encrypted snapshot, Ed25519, sync, and console passed |
| Capture performance | 10,000 events at 170.445 events/s; replay page p99 43.071 ms; bounded backpressure verified |
| Feature PR hosted CI | [Run 32635867425](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32635867425) passed Windows, macOS, and Ubuntu |
| Post-merge hosted CI | [Run 32636448594](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32636448594) passed all five jobs |
| Publication metadata PR CI | [Run 32640375142](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32640375142) passed all five jobs |
| Publication merge CI | [Run 32641467412](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32641467412) passed all five jobs |
| Nested-artifact privacy repair | [PR CI 32642651151](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32642651151) and [main CI 32643303151](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32643303151) passed |
| Large native-artifact privacy repair | [PR CI 32644657258](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32644657258) and [main CI 32645754456](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32645754456) passed |
| Final native release workflow | [Run 32646317248](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32646317248) passed Windows, macOS, and Linux |
| GitHub Pages deployment | [Run 32641467447](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32641467447) passed; rendered desktop and 390 px mobile checks found no browser errors or horizontal overflow |

The first two native-release attempts failed closed and were not accepted. They
identified incomplete scanning of an ignored nested artifact directory and a
Linux binary larger than the default 25 MiB scan ceiling. The fixes preserved
the 25 MiB archive-member limit while adding an explicit, hard-bounded 128 MiB
top-level release-artifact scan. Only the final green native run above supplied
the public release assets.

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

## Public Artifact Acceptance

On 2026-08-23, all eight public release assets were downloaded anonymously from
the formal GitHub prerelease. The seven files covered by `SHA256SUMS.txt` matched
their published SHA-256 values:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `rta_smriti_brain-0.9.0a1-py3-none-any.whl` | 494,920 | `9d698d2b75892f0d303b45619b4da3f9663adcaab80bc650cbe851fe1dc31b8b` |
| `rta-brain-0.9.0a1-linux-x86_64` | 32,849,128 | `eb81ef800462eb49244312fe6381158394fe13a7f36d6719ce392e9047ce7896` |
| `rta-brain-0.9.0a1-macos-arm64` | 16,851,760 | `2bdf79dd79b7f18db02e41168b52fdf7696baa33f69319c11fccaec2d1473d4d` |
| `rta-brain-0.9.0a1-windows-x86_64.exe` | 18,095,617 | `4588604261b92e213fd130257e9232e370dd1a77b6f16175aead0bf65829bd91` |
| Linux CycloneDX SBOM | 1,158 | `cf39121d7c7583c7877d75ebd939d6ccc5559583a601bfdc32300a800ce37c28` |
| macOS CycloneDX SBOM | 1,154 | `0717a3ba4cbccb5866fb18fa5c8a11327808ac9c60a0ea7c054f88e7a1ad9c3d` |
| Windows CycloneDX SBOM | 1,163 | `34d1128c251269ff9bb74695b135c0ecc1a7d1d3b065731e5e79acf93f52c18e` |

The public wheel installed successfully in a new Python 3.13 virtual
environment with its declared dependencies. From that clean environment,
`rta-brain --version` returned `0.9.0a1`; initialization in an owner-only brain
directory, repository ingestion, SHA-256 freshness, structured checkpointing,
continuation readiness, and the 24-tool MCP probe passed. The anonymously
downloaded Windows executable also returned `rta-brain 0.9.0a1`.

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
