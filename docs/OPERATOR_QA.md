# Rendered Operator QA

Rta-Smriti treats browser behavior as release evidence, not as a visual smoke test. The maintained
acceptance journey runs against a disposable, canonical Git repository and a real SQLite brain.

## Run It

```bash
npx playwright install chromium
npm run build
npm run test:unit
npm run test:operator
```

The test never reads a developer's existing projects. Its server fixture is created under the
operating system temporary directory and removed at the end of the run.

## Proven Journey

The Playwright journey verifies:

- authorized console load, project discovery, and healthy runtime state;
- random per-launch fixture authorization and rejection of the retired fixed token;
- every primary navigation destination with destination-specific regions, active-state semantics,
  named controls, and WCAG 2 A/AA plus WCAG 2.1 A/AA axe checks;
- watcher start and stop through the rendered Settings control;
- graph hub mouse and keyboard behavior, zoom, graph export, node selection, references, and Back;
- Canvas trace, keyboard inspection, JSON export, and a zero-overlap mobile card layout;
- continuation prompt copy, command copy, context-pack generation, and receipt creation;
- indexed file preview and Add to Task;
- blocking governance decision and an immutable operator override receipt;
- Intelligence tab semantics and arrow-key navigation;
- workspace creation, membership, cross-brain search, and persistence after reload;
- selective redacted export preview and export;
- authenticated snapshot creation and verification;
- opt-in Git hook installation and removal, plus conservative memory decay;
- command-palette focus containment, Escape close, and focus restoration;
- named-control detection, reduced motion, forced-colors structure, 720 px and 390 px overflow;
- clipboard-denial feedback and expected unauthenticated API rejection while normal operation
  remains console-clean;
- rendered onboarding of a second disposable project, automatic selection, watcher cleanup,
  exact database/project identity under a same-name wrong-root injection, duplicate-root warning,
  empty-project recovery, and refresh restoration;
- failed post-bootstrap identity verification that clears the previously selected project before
  another local action can target the wrong database;
- literal PowerShell and POSIX command serialization for substitutions, backticks, quotes, and
  embedded newlines, with both shells executed on the Windows release host.

CI installs Chromium and runs this journey on `windows-latest`, `macos-latest`, and
`ubuntu-latest` with Python 3.11. Backend unit and integration tests still cover hostile inputs,
race conditions, rollback, parser failures, and lower-level API contracts.

## Evidence Boundary

A green rendered journey proves the checked workflow on the named browser and CI image. It does not
claim compatibility with every browser, assistive technology, desktop environment, or third-party
agent. Axe does not substitute for a real screen reader, and its color-contrast rule is not applied
while Chromium remaps author colors in forced-colors mode; normal-mode contrast is checked on every
destination. Manual release review still checks current screenshots at desktop and mobile widths.
