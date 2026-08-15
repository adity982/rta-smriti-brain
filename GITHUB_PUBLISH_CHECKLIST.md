# GitHub Publish Checklist

## Repository Hygiene

- [ ] Confirm no private project files, SQLite brains, logs, thread exports, screenshots with private names, or local paths are committed.
- [ ] Confirm `.gitignore` excludes `.rta-smriti/`, `*.sqlite`, `*.log`, `*.out`, `*.err`, `__pycache__/`, `*.py[cod]`, `node_modules/`, and `*.egg-info/`.
- [ ] Confirm README examples use neutral paths such as `C:\path\to\my-project`.
- [ ] Confirm screenshots, if added later, use demo data only.

## Verification

Run from the repository root:

```powershell
npm install
npm run build
python scripts/privacy_scan.py
python -m unittest discover -s tests -v
python -m compileall -q rta_brain tests
pip install -e . --dry-run --no-deps
python rta-brain.py publish-readiness --json
gitleaks git --redact --no-banner --verbose .
gitleaks dir --redact --no-banner launch-assets
gitleaks dir --redact --no-banner launch-site/public
```

Smoke-test a temporary local brain:

```powershell
python rta-brain.py --db .\.rta-smriti\publish-smoke.sqlite --json init --project publish-smoke --root .
python rta-brain.py --db .\.rta-smriti\publish-smoke.sqlite --json ingest-repo . --project publish-smoke
python rta-brain.py --db .\.rta-smriti\publish-smoke.sqlite context-pack "prepare this repo for launch" --project publish-smoke
python rta-brain.py dashboard --brain-dir .\.rta-smriti --no-open
```

Delete `.rta-smriti/` after the smoke test.

## Suggested Initial Git Commands

```powershell
git init
git add .
git commit -m "feat: launch rta-smriti brain"
git branch -M main
git remote add origin <github-repo-url>
git push -u origin main
```

## GitHub Metadata

Repository name:

```text
rta-smriti-brain
```

Description:

```text
Local project memory and context packs for AI coding agents.
```

Topics:

```text
ai-memory, coding-agents, mcp, context-engineering, second-brain, sqlite, local-first, codex, claude-code, developer-tools
```

Maturity label:

```text
Alpha local-first project memory and MCP context-pack engine for AI coding agents.
```

## Before Product Hunt

- [ ] Add a clean demo screenshot or short video using demo data only.
- [ ] Create a public GitHub release.
- [ ] Prepare a 1-line tagline, maker comment, launch gallery, and first 3 comments.
- [ ] Prepare install instructions for Windows first; add macOS/Linux notes after wrapper support is tested.
- [ ] Invite trusted technical users to test the install flow before launch day.
