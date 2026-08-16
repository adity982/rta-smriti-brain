# Release Verification

This page records the reproducible checks for the local release candidate. It
is implementation evidence, not a substitute for green hosted CI, owner
approval, or a formal GitHub Release.

## Publication State

- Source version: `0.4.0-alpha` (`0.4.0a1` in Python package metadata)
- Local candidate branch: `release/unified-next`
- Target publication branch: `main`
- Formal `v0.4.0-alpha` Git tag: intentionally not created
- Formal `v0.4.0-alpha` GitHub Release: intentionally not created
- Latest historical tag: `v0.3.0-alpha`

No v0.4 source, tag, binary, or Release described by this candidate has been
published yet. Publication remains an explicit owner gate.

## Verification Commands

Run these commands from the repository root:

```powershell
npm run build
npm run build:launch
python -m unittest discover -s tests -v
python -m compileall -q rta_brain tests scripts
python -m build --wheel
python scripts/installed_distribution_smoke.py --wheel <wheel-path>
python -m pip install ".[binary]"
python scripts/build_binary.py
python scripts/smoke_binary.py
python scripts/privacy_scan.py
pip-audit . --progress-spinner off
python rta-brain.py publish-readiness --json
git diff --check
```

Optional release-environment checks:

```powershell
npm audit --omit=dev
pip install -e . --dry-run --no-deps
gitleaks git --redact --no-banner --verbose .
gitleaks dir --redact --no-banner launch-assets
gitleaks dir --redact --no-banner launch-site/public
```

## Current Verified Snapshot

Verified locally on Windows on 2026-08-16 before publication. The checked-in
workflow defines equivalent Windows, Ubuntu, and macOS jobs, but this exact
candidate is not considered cross-platform verified until those hosted jobs
run green after the owner-approved push.

| Gate | Result |
| --- | --- |
| Pytest regression suite | 167 passed, 4 platform/privilege skips, 513 subtests passed |
| Unittest discovery | 171 tests passed, 4 platform/privilege skips |
| Python bytecode compilation | Passed |
| Operator console production build | Passed |
| Launch-site production build | Passed |
| Root npm dependency audit | 0 vulnerabilities |
| Python project dependency audit | No known vulnerabilities reported by `pip-audit` |
| Editable Python package dry-run | Resolved `rta-smriti-brain-0.4.0a1` |
| Installed wheel first-run smoke | 20 checks passed, including bootstrap, retrieval, wrappers, MCP, managed watcher lifecycle, and console lifecycle from an unrelated working directory |
| Standalone Windows binary | Built from the versioned spec; CLI, SQLite/FTS, MCP dispatch, packaged dashboard assets, and managed background sync passed |
| Windows executable SHA-256 | `57b0221c032a5e4b4110aeb2405b45ef8ad7a7cc2bd60f142a605dde2cd342ad` |
| Universal wheel SHA-256 | `cbbdf07561977228ef864650ed554a7cd2129130af0e79e35a3f1170f6cf7f40` |
| Operator browser workflow | Six local projects loaded; Graph, Files, Canvas, Bases, references, task handoff, copy actions, agent selection, context packs, release checks, bootstrap, settings, and watcher controls passed at desktop and 390 px; 0 console warnings or errors |
| Publication privacy scan | Passed across 147 public candidates |
| Public benchmark | Six synthetic documents and queries; lexical and dependency-free hash-hybrid regression gates passed; this is not superiority evidence |
| Codex Security final diff scan | Complete, 35/35 review items, 0 findings (`ff1bbe20-368c-47b4-97ea-02924d455211`) |
| Built-in publish-readiness command | Structural gates passed; the clean-tree gate is re-evaluated on the frozen candidate commit before owner approval |
| Git whitespace validation | Passed |

The four skips are explicit platform or privilege conditions: Windows cannot
exercise POSIX mode bits, and this account cannot create the symlinks used by
three rejection tests. Hard-link, reparse-aware, descriptor-identity, and
replace-during-read controls remain exercised on Windows.

Hosted compatibility is accepted only when all three operating-system jobs are
green. Each job performs the dashboard builds, privacy scan, Python regression
suite, bytecode compilation, package-resolution check, clean-wheel install and
first-run smoke, and built-in publish-readiness check.

Gitleaks, Bandit, Ruff, and Semgrep were unavailable in the current shell, so
this page does not claim fresh results from any of them. The bundled privacy
scanner, dependency audits, focused hardening tests, and Codex Security scan
all passed; none is described as equivalent to an unavailable tool.

The final Windows executable and universal wheel are staged under the ignored
local release-artifact directory with a generated `SHA256SUMS.txt`; the manifest
was recomputed and matched both files. macOS and Linux binaries must be produced
and checksum-tested by the hosted matrix from the exact approved commit.

## Privacy Boundary

Public verification must not expose local brain databases, private repository
contents, user paths, capability tokens, private project names, or generated
context packs. Public screenshots and launch media use synthetic demo data.

See [Publishing Privacy](PUBLISHING_PRIVACY.md) for the complete procedure and
[Security Policy](../SECURITY.md) for vulnerability reporting.

## Historical Evidence

The original v0.3 launch-readiness snapshot is retained at
[`archive/LAUNCH_READINESS_v0.3.0-alpha.md`](archive/LAUNCH_READINESS_v0.3.0-alpha.md).
It is historical evidence and must not be interpreted as the current release
state.
