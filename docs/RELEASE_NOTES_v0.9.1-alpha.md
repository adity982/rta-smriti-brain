# Rta-Smriti Brain v0.9.1-alpha

`v0.9.1-alpha` is an operator-readiness patch for the Universal Capture
release. It preserves the v0.9 data model and trust boundaries while making the
multi-project dashboard and MCP gateway more predictable under real local load.
## Build Provenance

Conceived and researched by Sulabh Dubey. Built with [OpenAI Codex](https://openai.com/codex/) as the primary design, engineering, testing, and documentation agent under the maintainer's product direction and release approval. See [Contributors And Build Provenance](../CONTRIBUTORS.md).


## Operator Reliability

- Starts the dashboard from a lightweight authenticated registry snapshot, then
  loads repository, continuity, capture, checkpoint, and graph details
  progressively.
- Keeps usable project information visible while expensive freshness or
  continuity checks are still running.
- Uses bounded request timeouts and explicit `checking`, `stopped`, and
  `not configured` states instead of blank or misleading health indicators.
- Prevents delayed responses from a previously selected project from replacing
  the current graph, files, preview, capture, retrieval, governance, or truth
  state.
- Preserves the operator's newer project selection when a slower background
  registry refresh completes.
- Requires an explicit project argument in every advertised multi-project MCP
  gateway tool schema. Single-project MCP configurations remain project-bound.

## Local Qualification

The frozen Windows candidate passed:

- 788 Python tests, with 23 explicit platform or optional-capability skips;
- five dashboard unit tests;
- four adversarial progressive-loading and project-switch isolation journeys;
- seven complete rendered operator journeys covering files, graphs, canvas,
  capture, context packs, governance, MCP diagnostics, snapshots, workspaces,
  accessibility, mobile layout, and fault states;
- a real multi-project local audit with no browser console errors, failed API
  requests, persistent loading states, false integrity alerts, or horizontal
  mobile overflow;
- package build, installed-package dependency, npm dependency, privacy,
  Gitleaks, actionlint, and patch-integrity checks; and
- frozen Codex Security diff scans covering 13 of 13 operator-readiness
  implementation surfaces and 12 of 12 release/website code-bearing surfaces,
  with zero findings in either scan.

The frozen security scans covered the original operator-readiness and
release/website surfaces, not an independent audit of every historical line in
the repository. The later seven-entry concurrency repair was manually reviewed
and separately passed regression, privacy, secrets, dependency, workflow, and
patch-integrity checks; it is not misrepresented as part of those frozen scans.
Temporary local reports and private operator data are not release artifacts.

## Compatibility And Upgrade

The package version is `0.9.1a1`. The installed-package qualification upgrades
from the immutable `v0.9.0-alpha` tag. This patch introduces no database schema
migration and does not change Universal Capture retention, authority, or
promotion semantics.

Managed watchers, continuity workers, and capture daemons remain explicit,
local, opt-in lifecycle services. A stopped service is reported as stopped; the
dashboard does not silently enable persistent collection.

## Publication Evidence

- PR CI [run 32719412677](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32719412677)
  passed all five Windows, macOS, and Ubuntu jobs.
- Post-merge CI [run 32722109549](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32722109549)
  passed all five jobs. Its first Windows attempt reached rendered acceptance
  after all Python and installation checks, then hit runner-level
  `ERR_NO_BUFFER_SPACE`; one bounded rerun passed the complete job without a
  code change.
- Native workflow [run 32724105024](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32724105024)
  built, audited, smoke-tested, packaged, privacy-scanned, and uploaded all
  Windows, Linux, and macOS artifacts from the exact annotated tag.
- Pages workflow [run 32722110481](https://github.com/sulabhdubey/rta-smriti-brain/actions/runs/32722110481)
  deployed the current website. Public desktop and 390 px mobile checks found
  no console errors, WCAG A/AA violations, broken media, or horizontal overflow.
- All eight public release files were downloaded without authentication. Every
  manifested SHA-256 matched; the public Windows binary reported `0.9.1a1`, and
  the public wheel installed in a clean environment and passed `doctor`.

The existing `v0.9.0-alpha` release notes, screenshots, demo, hashes, and
verification record remain historical evidence and are not rewritten.
