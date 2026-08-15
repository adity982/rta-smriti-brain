# Historical Launch Readiness: v0.3.0-alpha

> **Archived snapshot:** This document records a pre-publication v0.3 review.
> It is retained for historical traceability and is not the current release
> state. See [`../RELEASE_VERIFICATION.md`](../RELEASE_VERIFICATION.md) for the
> current, reproducible verification record.

## Status At The Time

**Status:** Review-ready. Not published, tagged, or pushed.

**Release candidate:** `v0.3.0-alpha`

## What Was Ready

- Local-first Python and SQLite project brain with repository, thread, memory, graph, freshness, and context-pack workflows.
- Secure React operator console with project switching, graph, file explorer, canvas, bases, memory ledger, evidence inspector, bootstrap, and publish-readiness views.
- Generic agent bridge for Codex, Claude Code, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Aider, Windsurf, and custom agents.
- MCP server, CLI, reusable skill, bootstrap flow, and local command wrappers.
- Product launch site, Product Hunt gallery, GitHub social preview, editable Remotion project, and a 60-second launch video.
- Public documentation for installation, usage, privacy, security, contribution, governance, roadmap, release notes, and launch operations.

## Verification Evidence At The Time

| Gate | Recorded result |
| --- | --- |
| Python regression suite | 33 passed, 1 skipped |
| Python bytecode compilation | Passed |
| Operator console production build | Passed |
| Launch-site production build | Passed |
| Root npm dependency audit | 0 vulnerabilities |
| Launch-video npm dependency audit | 0 vulnerabilities |
| Publication privacy scan | Passed across 101 public candidates |
| Private-project deny-term scan | Passed |
| Git history secret scan | Passed with Gitleaks |
| Launch assets secret scan | Passed with Gitleaks |
| Browser smoke checks | Desktop and mobile passed |
| Video validation | H.264, 1920 x 1080, 30 fps, 60 seconds |

The skipped test exercised Windows symlink rejection. The machine account did
not hold the privilege required to create the test symlink. Hard-link rejection
and all other filesystem boundary tests passed.

## Privacy Boundary

- No local brain databases, repository contents, user paths, capability tokens, or private project names belonged in the public package.
- Synthetic `atlas-demo` data was the only project shown in public screenshots and launch media.
- Public candidates were scanned before release; media still required manual visual inspection.
- Dashboard capability tokens remained session-only and were removed from the browser URL after bootstrap.

## Human Approval Gates At The Time

1. Approve the launch page, screenshots, video, Product Hunt copy, and maker comment.
2. Choose the GitHub owner and final repository name, then replace public URL placeholders.
3. Upload the launch video to the selected public video host and add its final URL.
4. Choose the Product Hunt account, launch date, and maker profiles.
5. Commit the reviewed tree, create the release tag, push, enable GitHub Pages, and submit Product Hunt.

These gates describe the historical pre-publication state only.
