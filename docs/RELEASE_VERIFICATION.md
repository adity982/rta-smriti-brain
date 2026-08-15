# Release Verification

This page records the reproducible publication checks for the source currently
available on `main`. It is evidence for the public repository, not a substitute
for CI results or a formal GitHub Release.

## Publication State

- Source version: `0.4.0-alpha` (`0.4.0a1` in Python package metadata)
- Published branch: `main`
- Formal `v0.4.0-alpha` Git tag: intentionally not created
- Formal `v0.4.0-alpha` GitHub Release: intentionally not created
- Latest historical tag: `v0.3.0-alpha`

The v0.4 source is therefore a verified update on `main`, not a tagged release.

## Verification Commands

Run these commands from the repository root:

```powershell
npm run build
npm run build:launch
python -m unittest discover -s tests -v
python -m compileall -q rta_brain tests
python scripts/privacy_scan.py
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

Verified on 2026-08-15 before publishing the documentation update:

| Gate | Result |
| --- | --- |
| Python regression suite | 43 passed, 1 skipped |
| Python bytecode compilation | Passed |
| Operator console production build | Passed |
| Launch-site production build | Passed |
| Root npm dependency audit | 0 vulnerabilities |
| Editable Python package dry-run | Resolved `rta-smriti-brain-0.4.0a1` |
| Installed wheel first-run smoke | 10 checks passed |
| Publication privacy scan | Passed across 109 public candidates |
| Built-in publish-readiness command | Structural gates passed; clean-tree gate confirmed after commit |
| Git whitespace validation | Passed |

The Windows symlink-rejection test may skip when the current account cannot
create symbolic links. A skip is reported explicitly rather than counted as a
pass.

Gitleaks is an optional release-environment check and is not claimed in this
snapshot because it was unavailable in the verification shell. The bundled
privacy scanner remains a required gate and passed.

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
