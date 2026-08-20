# Release Verification

This page records the reproducible checks and publication evidence for the
formal `v0.5.0-alpha` prerelease. It distinguishes local verification, hosted
CI, native binary workflow proof, and post-publication installation proof.

## Publication State

- Source version: `0.5.0-alpha` (`0.5.0a1` in Python package metadata)
- Published branch: `main`
- Frozen release commit: `be534d98e26dcc29e4028fb1027f904c8df30187`
- Formal Git tag: `v0.5.0-alpha` (annotated and verified against the frozen commit)
- Formal GitHub Release: [`Rta-Smriti Brain v0.5.0-alpha`](https://github.com/sulabhdubey/rta-smriti-brain/releases/tag/v0.5.0-alpha)
- Release state: published prerelease from the green hosted matrix
- Current `main` status: public README, documentation, and launch-site source
  describe the formal prerelease; the release tag and assets remain bound to the
  frozen commit above

The release contains Windows x64, Linux x64, and macOS binaries plus a combined
SHA-256 manifest. GitHub-generated source archives are also available from the
tag.

## v0.5.0-alpha Release State

This release adds the Trust + Retrieval Intelligence batch on top of the
published v0.4 continuity foundation: operational preflight warnings, retrieval selection
reasons, exact dashboard default-brain selection, root-level managed-console
`--db` parsing, and one-command onboarding continuity capture.

Latest release evidence from the C-drive release checkout:

| Release gate | Result |
| --- | --- |
| Dashboard production build | Passed |
| Launch-site production build | Passed |
| Dashboard unit tests | 5 passed |
| Operator browser QA | 2 passed |
| Launch-site browser QA | Passed: desktop, mobile, interactions, media, links, accessibility |
| Python unittest discovery | 224 tests passed, 9 skipped |
| Python bytecode compilation | Passed |
| npm audit high severity gate | 0 vulnerabilities |
| Editable install dry run | Would install `rta-smriti-brain-0.5.0a1` |
| Installed-distribution smoke | Passed install, upgrade, and uninstall lifecycle |
| Public benchmark | Synthetic corpus passed lexical, hash-hybrid, continuation, contradiction, stale, and governance gates |
| Privacy scan | 170 candidate files passed |
| Git diff whitespace check | Passed with only Windows LF-to-CRLF warnings |
| Built-in publish-readiness | Structural checks passed before publication; clean tree after commit and push |
| Dogfood brain freshness | 147 indexed sources fresh; 0 added, 0 changed, 0 missing |
| Hosted CI | [Run 32407147824](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32407147824) passed Ubuntu Python 3.11, 3.12, 3.13, macOS Python 3.11, and Windows Python 3.11 |
| Native binaries | [Run 32417096347](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32417096347) built and smoke-tested Windows, Linux, and macOS artifacts |
| Published release assets | `rta-brain-v0.5.0-alpha-windows-x64.exe`, `rta-brain-v0.5.0-alpha-linux-x64`, `rta-brain-v0.5.0-alpha-macos`, and `SHA256SUMS.txt` uploaded |
| Public release smoke | Windows asset redownloaded from the public release URL, checksum-verified, and `--version` returned `rta-brain 0.5.0a1` |

Do not claim Gitleaks, Bandit, Ruff, or Semgrep unless those tools were
available and actually run in the release shell. This v0.5 release does not
claim fresh results from those unavailable tools.

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
python scripts/privacy_scan.py --root .
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

## v0.4 Historical Verified Snapshot

The following snapshot is retained for the refreshed `v0.4.0-alpha` release.
It is historical evidence and must not be interpreted as the current v0.5
release state.

Verified locally and through GitHub Actions. The refreshed formal release is
bound to [CI run 32302463544](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32302463544),
which passed on Windows, macOS, Ubuntu Python 3.11, Ubuntu Python 3.12, and
Ubuntu Python 3.13 before the tag and assets were refreshed.

| Gate | Result |
| --- | --- |
| Pytest regression suite | 176 passed, 6 platform/privilege skips, 513 subtests passed |
| Unittest discovery | 182 tests passed, 6 platform/privilege skips |
| Python bytecode compilation | Passed |
| Operator console production build | Passed |
| Launch-site production build | Passed |
| Root npm dependency audit | 0 vulnerabilities |
| Python runtime dependency surface | Core wheel has no required third-party dependencies; isolated install and both entry points passed |
| Python project dependency audit | `pip-audit .` reported no known vulnerabilities |
| Editable Python package dry-run | Resolved `rta-smriti-brain-0.4.0a1` |
| Installed package lifecycle | Clean wheel install and 20-check first-run smoke passed; forced upgrade/reinstall and uninstall were then verified from an unrelated working directory |
| Standalone Windows binary | Built from the versioned spec; CLI, SQLite/FTS, MCP dispatch, packaged dashboard assets, public benchmark, managed background sync, and managed console lifecycle passed |
| Windows executable SHA-256 | `f934f74c251dd2dbaca21ef26ad03ab21635bf725c5598bb361fe7419f23d406` |
| Linux executable SHA-256 | `73723745b84efeb2a0db6f58f1e6859c6c1daae04869ea1a2aa0b5dc0e2ef1ff` |
| macOS executable SHA-256 | `4875357a5bb4b3f4d07c954f3398179fb6175ee9f6f4b80c03d59cd31e8dd7ab` |
| Universal wheel SHA-256 | `a371e9f8050e4b6ee079e476ab40002b1aceb64adf53b94390081cf4cac9ce5c` |
| Automated rendered operator acceptance | Playwright exercised every primary destination, destination-wide axe checks, onboarding/selection, root-conflict and empty-project recovery, Graph, Files, Canvas, task handoff, clipboard failure, watcher controls, governance receipts, Intelligence, workspaces, vault, hooks, persistence, keyboard focus, reduced motion, forced-colors structure, and 720/390 px layouts. A second failure-injection scenario proves that failed post-bootstrap identity verification clears the previous project; 2 scenarios passed with no unexpected page or console errors |
| Manual operator browser workflow | Six local projects loaded; Graph, Files, Canvas, Bases, references, task handoff, agent selection, context packs, release checks, bootstrap, settings, and watcher controls passed at desktop and 390 px |
| Accessibility repair | Intelligence and Bases tabs expose tab semantics and roving keyboard focus; Bases exposes table, row-group, row, header, and cell relationships; exactly one route is current; toolbar toggles expose state; graph search and workspace fields have names; status changes are live; modal focus is trapped/restored; keyboard Canvas inspection focuses and reveals the mobile inspector; normal-mode WCAG scans passed every destination; mobile Canvas cards had zero overlaps |
| Performance and resource probe | Sanitized synthetic baselines passed at 100, 1,000, and 10,000 files; the committed JSON reports indexing, deep freshness, search/context-pack p95, SQLite size, and traced peak memory without hostnames or absolute paths |
| Publication privacy scan | Passed across 169 public candidates, including the website, screenshots, gallery, poster, and video |
| Launch-site operator acceptance | Built-site Playwright journey passed at desktop and 390 px: product and evidence tabs, mobile navigation, media metadata, local asset links, horizontal overflow, WCAG axe scans, and console/page errors |
| Public benchmark | Six synthetic documents and queries; lexical and dependency-free hash-hybrid regression gates passed; this is not superiority evidence |
| Codex Security remediation scan | A frozen pre-fix snapshot reviewed 18 changed runtime artifacts across eight threat surfaces and reproduced one low-severity stale-selection issue (`bf16b280-16e1-4d67-8d2a-08e7f83fab4e`). The issue is fixed and covered by a failing-then-passing rendered test. This scan is remediation evidence, not the final clean-tree gate |
| Codex Security exact-commit gate | Full-candidate scan `c75b2a3f-4330-4f04-a0eb-c4655a37481d` and final runtime-diff scan `7d6952ce-130a-4746-8db4-c98b9a195d89` completed with full coverage and zero findings; the final follow-up changed test assertions only |
| Built-in publish-readiness command | 11/11 structural and clean-tree checks passed on the candidate before publication |
| Git whitespace validation | Passed |
| Hosted compatibility | Final `main` matrix passed Windows x64, macOS ARM64, and Ubuntu with Python 3.11, 3.12, and 3.13 |
| Published assets | Six refreshed release assets uploaded from the green hosted run; public downloads match the recomputed combined manifest |
| Post-publish installation | Every refreshed public asset redownloaded and checksum-verified; staged Windows binary `--version` and `doctor` passed |

The six local skips are explicit platform or privilege conditions. Windows
cannot exercise POSIX mode bits, and this account cannot create the symlinks
used by rejection tests. The hosted macOS and Linux jobs exercise their native
paths; hard-link, reparse-aware, descriptor-identity, and replace-during-read
controls remain exercised on Windows.

Each hosted job performed the dashboard builds, privacy scan, Python regression
suite, bytecode compilation, package-resolution check, clean-wheel install and
first-run smoke, and built-in publish-readiness check. The final matrix passed
before the release tag was refreshed.

Gitleaks, Bandit, Ruff, and Semgrep were unavailable in the current shell, so
this page does not claim fresh results from any of them. The bundled privacy
scanner, dependency audits, focused hardening tests, and Codex Security scan
all passed; none is described as equivalent to an unavailable tool.

Launch screenshots, gallery images, poster, and video were regenerated from the
current synthetic fixture and launch source. Product Hunt and website video and
poster copies match byte-for-byte; private-project scale claims are not accepted
as launch evidence.

The final wheel and three native binaries were produced and smoke-tested by the
hosted matrix from the approved commit. The six public release assets were then
downloaded again, and every file matched the published `SHA256SUMS.txt`.

## Refreshed v0.4 Alpha Scope

The refreshed `v0.4.0-alpha` release includes the continuity hardening batch:
managed transcript capture, append-only session events, structured work-state
reconciliation, operational readiness, and a fail-closed multi-project MCP
gateway. Local verification for that batch covered unit tests, bytecode
compilation, dashboard and launch builds, dependency audits, wheel and binary
smoke tests, privacy scan, presentation-mode media sanitization, and six-project
daemon status. Hosted CI then passed on the refreshed commit before publication.

Gitleaks is an optional release-environment check and is not claimed in this
snapshot. The bundled privacy scanner remains a required gate and passed; this
page does not imply that the two tools are equivalent.

Codex host configuration was generated, added to the local Codex configuration,
parsed successfully, and exercised against the multi-project MCP gateway over
stdio. Existing Codex tasks still cannot dynamically acquire newly registered
MCP tools; a fresh task must be started after host configuration changes.

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
