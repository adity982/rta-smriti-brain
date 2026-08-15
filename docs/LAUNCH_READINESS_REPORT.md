# Rta-Smriti Brain Launch Readiness

**Status:** Review-ready. Not published, tagged, or pushed.

**Release candidate:** `v0.3.0-alpha`

## What Is Ready

- Local-first Python and SQLite project brain with repository, thread, memory, graph, freshness, and context-pack workflows.
- Secure React operator console with project switching, graph, file explorer, canvas, bases, memory ledger, evidence inspector, bootstrap, and publish-readiness views.
- Generic agent bridge for Codex, Claude Code, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Aider, Windsurf, and custom agents.
- MCP server, CLI, reusable skill, bootstrap flow, and local command wrappers.
- Product launch site, Product Hunt gallery, GitHub social preview, editable Remotion project, and a 60-second launch video.
- Public documentation for installation, usage, privacy, security, contribution, governance, roadmap, release notes, and launch operations.

## Verification Evidence

| Gate | Result |
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

The skipped test exercises Windows symlink rejection. This machine account does not hold the privilege required to create the test symlink. Hard-link rejection and all other filesystem boundary tests passed.

## Security Qualification

The initial independent scan identified dashboard authorization, origin, filesystem-link, parser-bounds, prompt-boundary, workflow-permission, receipt-storage, and privacy risks. These were remediated and regression-tested.

The post-remediation review validated the major fixes and identified one additional low-severity publication-scan coverage gap. The scanner now checks command files, UTF-8 paths, UTF-16 metadata, and printable media metadata without interpreting compressed payload bytes. The final authoritative security report is generated as the last local release gate.

## Privacy Boundary

- No local brain databases, repository contents, user paths, capability tokens, or private project names belong in the public package.
- Synthetic `atlas-demo` data is the only project shown in public screenshots and launch media.
- Public candidates are scanned before release; media still receives a manual visual inspection.
- Dashboard capability tokens remain session-only and are removed from the browser URL after bootstrap.

## Human Approval Gates

1. Approve the launch page, screenshots, video, Product Hunt copy, and maker comment.
2. Choose the GitHub owner and final repository name, then replace public URL placeholders.
3. Upload the launch video to the selected public video host and add its final URL.
4. Choose the Product Hunt account, launch date, and maker profiles.
5. Commit the reviewed tree, create the release tag, push, enable GitHub Pages, and submit Product Hunt.

## Review Map

- Product introduction: `README.md`
- Product Hunt and launch copy: `docs/LAUNCH_KIT.md`
- Asset inventory: `launch-assets/ASSET_MANIFEST.md`
- Brand rules: `launch-assets/BRAND_GUIDE.md`
- Privacy procedure: `docs/PUBLISHING_PRIVACY.md`
- Security policy: `SECURITY.md`
- Release notes: `docs/RELEASE_NOTES_v0.3.0-alpha.md`
- Publish checklist: `GITHUB_PUBLISH_CHECKLIST.md`

The only expected publish-readiness check still open before approval is a clean Git working tree. That check becomes green after the reviewed release files are committed.
