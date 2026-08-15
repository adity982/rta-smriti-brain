# Contributing

Rta-Smriti Brain is intentionally dependency-light. Keep changes local-first, test-first, and inspectable.

## Development

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Compile check:

```powershell
python -m compileall -q rta_brain tests
```

Build the packaged console and launch site:

```powershell
npm ci
npm run build
npm run build:launch
```

## Design Rules

- Prefer deterministic retrieval and explicit provenance over opaque automation.
- Keep project memory isolated by default.
- Do not add network calls without a clear opt-in setting.
- Do not store secrets.
- Add tests before behavior changes.
- Keep MCP tools narrow and composable.

## Release Checklist

- Tests pass.
- Compile check passes.
- README examples match the current CLI.
- `SECURITY.md` is current.
- MIT license, release notes, and changelog are current.
- Public screenshots use only the synthetic Atlas demo.
- No SQLite brains, context packs, private paths, thread exports, credentials, or real project data are tracked.
- `python rta-brain.py publish-readiness --json` passes.
