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
npm run test:unit
npx playwright install chromium
npm run test:operator
python scripts/performance_probe.py --profiles 100 1000 --assert-bounds
python -m unittest discover -s tests -v
python -m pytest -q
python -m compileall -q rta_brain tests scripts
python scripts/build_installed_smoke.py
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
| Pytest regression suite | 169 passed, 4 platform/privilege skips, 513 subtests passed |
| Unittest discovery | 173 tests passed, 4 platform/privilege skips |
| Python bytecode compilation | Passed |
| Operator console production build | Passed |
| Launch-site production build | Passed |
| Root npm dependency audit | 0 vulnerabilities |
| Python project dependency audit | No known vulnerabilities reported by `pip-audit` |
| Editable Python package dry-run | Resolved `rta-smriti-brain-0.4.0a1` |
| Installed package lifecycle | Clean wheel install and 20-check first-run smoke passed; forced upgrade/reinstall and uninstall were then verified from an unrelated working directory |
| Standalone Windows binary | Built from the versioned spec; CLI, SQLite/FTS, MCP dispatch, packaged dashboard assets, public benchmark, managed background sync, and managed console lifecycle passed |
| Windows executable SHA-256 | `a246d081d76b654395cecdd9d6f20ca683fc74bd5ffa6b9699716434e9acc7c1` |
| Universal wheel SHA-256 | `e487fe47f044c2d113a91012eeba32701ff854ac08a5a98d5a3d149b5ad16dc2` |
| Automated rendered operator acceptance | Playwright exercised every primary destination, destination-wide axe checks, onboarding/selection, root-conflict and empty-project recovery, Graph, Files, Canvas, task handoff, clipboard failure, watcher controls, governance receipts, Intelligence, workspaces, vault, hooks, persistence, keyboard focus, reduced motion, forced-colors structure, and 720/390 px layouts. A second failure-injection scenario proves that failed post-bootstrap identity verification clears the previous project; 2 scenarios passed with no unexpected page or console errors |
| Manual operator browser workflow | Six local projects loaded; Graph, Files, Canvas, Bases, references, task handoff, agent selection, context packs, release checks, bootstrap, settings, and watcher controls passed at desktop and 390 px |
| Accessibility repair | Intelligence and Bases tabs expose tab semantics and roving keyboard focus; Bases exposes table, row-group, row, header, and cell relationships; exactly one route is current; toolbar toggles expose state; graph search and workspace fields have names; status changes are live; modal focus is trapped/restored; keyboard Canvas inspection focuses and reveals the mobile inspector; normal-mode WCAG scans passed every destination; mobile Canvas cards had zero overlaps |
| Performance and resource probe | Sanitized synthetic baselines passed at 100, 1,000, and 10,000 files; the committed JSON reports indexing, deep freshness, search/context-pack p95, SQLite size, and traced peak memory without hostnames or absolute paths |
| Publication privacy scan | Passed across 163 public candidates, including the refreshed website, screenshots, gallery, poster, and video |
| Launch-site operator acceptance | Built-site Playwright journey passed at desktop and 390 px: product and evidence tabs, mobile navigation, media metadata, local asset links, horizontal overflow, WCAG axe scans, and console/page errors |
| Public benchmark | Six synthetic documents and queries; lexical and dependency-free hash-hybrid regression gates passed; this is not superiority evidence |
| Codex Security remediation scan | A frozen pre-fix snapshot reviewed 18 changed runtime artifacts across eight threat surfaces and reproduced one low-severity stale-selection issue (`bf16b280-16e1-4d67-8d2a-08e7f83fab4e`). The issue is fixed and covered by a failing-then-passing rendered test. This scan is remediation evidence, not the final clean-tree gate |
| Codex Security exact-commit gate | The previous release-candidate commit `259bba6` passed an immutable 17-artifact, eight-surface scan with zero findings. The final asset-refresh commit must independently pass the same zero-finding gate before owner approval |
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

Launch screenshots, gallery images, poster, and video were regenerated from the
current synthetic fixture and launch source. Product Hunt and website video and
poster copies match byte-for-byte; private-project scale claims are not accepted
as launch evidence.

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
