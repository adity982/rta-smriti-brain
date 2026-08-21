# Unified Release Completion Audit

This audit maps the unified release objective to current evidence. A passing test is credited only
for the behavior it directly exercises.

| Requirement Area | State | Authoritative Evidence |
| --- | --- | --- |
| Managed console lifecycle and recovery | Released and verified | `tests/test_managed_console.py`, installed distribution smoke, final hosted matrix |
| Optional login startup | Released and verified | `tests/test_autostart.py` and final hosted OS matrix |
| Canonical-root one-command onboarding | Released and verified | `tests/test_onboarding.py`, installed distribution smoke, final hosted matrix |
| Watcher, warmed hash cache, metadata-only isolation, strict mode, rollback | Candidate verified locally | feedback, resilience, ingestion-security, continuity, and operator suites |
| Lexical, hash-hybrid, optional semantic diagnostics | Released and verified | retrieval diagnostics and public benchmark suites |
| Bundled Tree-sitter, regex fallback, discovered native LSP, custom adapters | Candidate verified locally | parser registry, bounded JSON-RPC, project-local rejection, and ecosystem extraction tests |
| Structured checkpoints and provenance | Released and verified | blueprint, feedback, context, CLI, API, MCP, and continuity tests |
| Pramana-aware action governance | Released and verified | governance unit/API/MCP tests and rendered block/override journey |
| Bounded graph, dependents, impact, evidence, relevance | Released and verified | release-intelligence tests and rendered graph/reference journey |
| Privacy-safe public benchmark | Released and verified | packaged corpus digest, multimode metrics, quality gates, and published benchmark asset |
| Reinforcement and conservative decay | Released and verified | lifecycle tests and rendered operator action |
| Isolated multi-brain workspaces | Released and verified | workspace tests and persisted rendered workflow |
| Selective redacted export/import | Released and verified | staged validation, hostile bundle tests, rendered preview/export |
| Encrypted and authenticated local snapshots | Candidate verified locally | AES-GCM, Ed25519, HMAC, tamper/size/link, and rendered create/verify tests |
| Opt-in Git hooks | Released and verified | linked-worktree/security tests and rendered on/off workflow |
| Accessibility and responsive behavior | Released and verified | destination-wide axe WCAG checks, tab/navigation state, focus containment, live announcements, clipboard failure, reduced motion, forced-colors structure, and zero-overlap mobile Canvas |
| Small-to-large resource evidence | Released and verified | `benchmarks/performance-baseline-v1.json` and bounded CI probe |
| Install, upgrade/reinstall, uninstall | Released and verified | isolated wheel lifecycle smoke |
| Shell-safe generated commands and exact bootstrap identity | Released and verified | executable PowerShell/POSIX hostile-path tests plus rendered duplicate-root and failed-verification scenarios |
| Final security and privacy review | Candidate verified locally | Gitleaks 8.30.1 scanned 53 commits with no leaks; actionlint passed; repository privacy scan passed 174 candidate files; npm and isolated Python dependency audits reported no known runtime vulnerabilities |
| Privacy-safe launch website and media | Candidate verified locally | launch-site desktop/mobile interaction, link, media, and accessibility QA passed against public synthetic fixtures |
| Windows execution | Candidate verified locally | Python 3.13 suite, installed lifecycle, performance probe, rendered operator QA, and frozen executable smoke passed on Windows 11 |
| macOS and Linux execution | Pending hosted v0.6 gates | the workflow matrix is defined, but prior-release CI is not claimed as v0.6 evidence |
| Release artifacts for every OS | Pending hosted v0.6 gates | the Windows executable and wheel stage locally with SHA-256 checksums; macOS/Linux artifacts must come from the v0.6 hosted matrix |
| v0.6 tag, formal GitHub Release, links, post-publish install | Pending owner and hosted gates | no public v0.6 tag or Release is claimed by this candidate |

## Local Candidate Receipts

- Python: `251` passed, `9` platform-specific skips, `0` failures.
- Dashboard: `5` unit tests passed; dashboard and launch production builds passed.
- Rendered operator QA: `2` complete dashboard scenarios passed, including the new indexing,
  LSP discovery, and Ollama compaction settings persistence path.
- Launch-site QA: desktop, mobile, interactions, media, links, and accessibility passed.
- Installed lifecycle: clean install, upgrade, and uninstall passed.
- Standalone Windows binary: CLI, SQLite/FTS, MCP, bundled Tree-sitter, encrypted and Ed25519
  snapshots, background sync, and managed console lifecycle passed.
- Performance probe: `100`- and `1,000`-file synthetic profiles passed their bounded assertions.
- Supply chain: `npm audit --audit-level=high` and an isolated `pip-audit` run reported no known
  runtime dependency vulnerabilities.
- Publication safety: Gitleaks, actionlint, and the repository privacy scanner passed locally.

These are local candidate receipts, not hosted CI or public-release evidence.

## Residual Risks

- Optional Sentence Transformers behavior depends on a separately installed provider and model; the
  public benchmark reports unavailable/not-requested states instead of inventing semantic scores.
- Native LSP quality depends on the discovered third-party language server. Rta-Smriti bounds its
  client, rejects project-local discovery, and falls back safely, but cannot certify external server behavior.
- HMAC and signature-only snapshots are authenticated but not encrypted. Encrypted snapshots protect
  content at rest; every snapshot and key remains private and is not a safe public export.
- Performance evidence is synthetic and environment-specific. It is useful for regression detection,
  not a promise for every repository or machine.
- Automated WCAG and keyboard checks do not substitute for testing every operating-system screen
  reader, browser zoom implementation, or third-party assistive technology.
- Native binaries are alpha artifacts and are not platform code-signed. Operators must verify the
  release manifest and may need an explicit Windows SmartScreen or macOS Gatekeeper trust decision.
