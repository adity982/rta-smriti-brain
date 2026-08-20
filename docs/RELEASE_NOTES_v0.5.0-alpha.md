# Rta-Smriti Brain v0.5.0-alpha Candidate

This is the candidate note for the next formal prerelease. It should become the
GitHub Release body only after the reviewed commit is tagged and hosted CI
passes.

## Theme

`v0.5.0-alpha` turns the v0.4 continuity foundation into a more trustworthy
operator loop:

- actions get checked before they are taken;
- retrieval explains why each result was selected;
- the dashboard opens the intended project brain instead of falling back to the
  first available database;
- onboarding starts repository sync, the managed console, and Codex continuity
  capture together when the local sessions folder is present.

## New And Improved

- Pre-action governance can include operational context: checkpoint readiness,
  continuity lifecycle, dirty worktree state, canonical-root risk, and freshness.
- Retrieval diagnostics now include normalized query terms and per-result
  selection reasons for lexical, structural, and hybrid matches.
- Managed console startup preserves root-level `--db` for `dashboard` and
  `console start`, so a copied or custom brain directory opens the requested
  database instead of defaulting to the first brain.
- Dashboard health defaults are converted into an exact project/database
  identity, preserving fail-closed protection for duplicate project names.
- One-command `start` onboarding starts Codex continuity capture when the
  sessions folder exists, skips it explicitly when unavailable, and exposes
  controls for sessions root, interval, inactivity, lookback, and backlog tail.
- The multi-project MCP gateway and native MCP tools remain read-oriented and
  project-scoped; existing Codex tasks still need a fresh task after MCP
  registration changes.

## Fixes

- Fixed the copied-repo/local-console path where `rta-brain --db ... console
  start` launched successfully but the React dashboard did not auto-select the
  requested brain.
- Fixed the dashboard state flow so `/api/health` `default_db` and
  `default_project` select only the exact matching brain.
- Kept context-pack buttons observable: New Task Prompt and Copy Command now
  surface visible copied-state feedback in the operator console.

## Boundaries

- No hosted accounts, telemetry, cloud sync, privileged service, or automatic
  reboot persistence is added.
- Optional Sentence Transformers and LSP adapters remain operator-installed and
  operator-selected.
- Gitleaks is not claimed unless it is available and run in the release
  environment.
- Public release evidence must use synthetic data only. Local brain databases,
  private project paths, capability tokens, context packs, daemon state, and
  scratch artifacts are not release assets.

## Candidate Gates

Before tagging `v0.5.0-alpha`, run:

```powershell
npm audit --audit-level=high
npm run build
npm run build:launch
npm run test:unit
npm run test:operator
npm run test:launch
python -m unittest discover -s tests -v
python -m compileall -q rta_brain tests scripts
pip install -e . --dry-run --no-deps
python scripts/build_installed_smoke.py
python -m rta_brain.cli --json benchmark
python scripts/privacy_scan.py --root .
python -m rta_brain.cli publish-readiness --json
git diff --check
```

Then commit the reviewed tree, wait for hosted Windows/macOS/Linux CI, create
the annotated `v0.5.0-alpha` tag, build/upload release assets, verify
`SHA256SUMS.txt`, and perform a clean install from the public release page.
