# Contributing

Rta-Smriti Brain is intentionally local-first, dependency-light, and inspectable. Small, well-tested contributions are welcome.

## Choose A Starting Point

- Browse [`good first issue`](https://github.com/sulabhdubey/rta-smriti-brain/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) for bounded tasks with acceptance criteria.
- Browse [`help wanted`](https://github.com/sulabhdubey/rta-smriti-brain/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) for larger tasks where maintainer context is available.
- Ask an installation or design question in [Q&A](https://github.com/sulabhdubey/rta-smriti-brain/discussions/categories/q-a).
- Propose an idea in [Ideas](https://github.com/sulabhdubey/rta-smriti-brain/discussions/categories/ideas) before building a broad feature.

Comment on the issue you want to take before starting. That prevents duplicate work and gives us a chance to confirm the boundary.

## A 15-Minute First Contribution

Documentation, synthetic fixtures, and focused regression tests are good first contributions:

1. Fork the repository and create a short-lived branch.
2. Make one focused change tied to an open issue.
3. Add or update the smallest test that proves the change.
4. Run the focused test and the privacy test.
5. Open a pull request using the repository template.

Do not include a real brain database, context pack, transcript, local path, credential, or private project excerpt. Use the synthetic fixtures under `tests/fixtures/` and `rta_brain/data/`.

## Development

Create a Python 3.11+ virtual environment and install the project:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e .
```

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
```

Run the focused test first, then the full Python suite:

```powershell
python -m unittest tests.test_community_health -v
python -m unittest discover -s tests -v
```

Compile check:

```powershell
python -m compileall -q rta_brain tests scripts
```

Build the packaged console and launch site:

```powershell
npm ci
npm run build
npm run build:launch
```

Dashboard behavior changes also require the rendered operator suite:

```powershell
npx playwright install chromium
npm run test:operator
```

See [Operator QA](docs/OPERATOR_QA.md) for the browser acceptance boundary.

## Design Rules

- Prefer deterministic retrieval and explicit provenance over opaque automation.
- Keep project memory isolated by default.
- Do not add network calls without a clear opt-in setting.
- Do not store secrets.
- Add tests before behavior changes.
- Keep MCP tools narrow and composable.

## Pull Request Scope

- Keep each pull request tied to one issue or one coherent outcome.
- Explain the operator problem, the behavior change, and the evidence in the pull-request body.
- Add tests for changed behavior and update user-facing documentation when commands or workflows change.
- Preserve cross-platform behavior on Windows, macOS, and Linux.
- Avoid unrelated formatting, generated-asset, dependency, or metadata churn.

The maintainer target is to acknowledge a focused pull request within three business days. This is an alpha community project, so complex reviews may take longer; review status will be communicated on the pull request.

## Questions And Security

Use [GitHub Discussions](https://github.com/sulabhdubey/rta-smriti-brain/discussions) for installation help, design questions, and early ideas. Use an issue for a reproducible public bug.

Do not open a public issue for a vulnerability or include exploit details in Discussions. Follow [SECURITY.md](SECURITY.md) and use [private vulnerability reporting](https://github.com/sulabhdubey/rta-smriti-brain/security/advisories/new).

## Release Checklist

- Tests pass.
- Compile check passes.
- README examples match the current CLI.
- `SECURITY.md` is current.
- MIT license, release notes, and changelog are current.
- Public screenshots use only the synthetic Atlas demo.
- No SQLite brains, context packs, private paths, thread exports, credentials, or real project data are tracked.
- `python rta-brain.py publish-readiness --json` passes.
