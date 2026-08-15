# Rta-Smriti Brain

![Rta-Smriti Brain - Give every project a memory](launch-assets/social/github-social-preview.png)

**A local project brain for AI coding agents.**

[Live website](https://sulabhdubey.github.io/rta-smriti-brain/) · [60-second product demo](launch-assets/product-hunt/rta-smriti-launch-demo.mp4) · [Installation](docs/INSTALLATION.md) · [Usage guide](docs/USAGE_GUIDE.md) · [Architecture](docs/ARCHITECTURE.md) · [Release verification](docs/RELEASE_VERIFICATION.md) · [Security](SECURITY.md) · [Roadmap](ROADMAP.md)

Rta-Smriti Brain turns a project repository, long agent threads, durable decisions, and evidence into a small local memory graph that Codex, Claude Code, Cursor, or any MCP-capable agent can reuse before doing work.

It is built for the moment every AI-assisted developer knows too well:

> "New chat. Same project. Same explanations. Same lost context."

Rta-Smriti gives each project a memory that stays on your machine.

## What It Does

- Indexes your repo into local SQLite: files, chunks, symbols, imports, and graph edges.
- Stores durable memories: decisions, constraints, procedures, facts, and hypotheses.
- Binds every project brain to one canonical root and refuses silent checkout switching.
- Records structured checkpoints: objective, verified evidence, remaining gaps, next action, and prohibited repetition.
- Attaches source path, hash, verification command, timestamp, and verification status to remembered claims.
- Ingests long threads or handoff notes as explicitly unverified prior memory so useful context survives compaction without self-assigning trust.
- Builds a focused **context pack** for the next agent task.
- Runs a local operator console with graph, canvas, typed bases, context-pack receipts, memory ledger, freshness checks, and bootstrap flow.
- Exposes a dependency-light stdio MCP server for agent integrations.
- Watches active repositories with a foreground incremental indexer and reuses a persistent SHA-256 cache for deep freshness checks.
- Supports optional local hybrid retrieval through a built-in deterministic hash provider or an installed Sentence Transformers model.
- Supports built-in regex parsing plus optional Tree-sitter and explicit LSP adapter commands.
- Keeps data local by default: no API keys, no telemetry, no cloud database.

## Why It Is Different

Most second-brain tools store notes. Most code tools index files. Most agent memory systems recall text.

Rta-Smriti combines all three into a small, inspectable project brain:

| Layer | What it adds |
| --- | --- |
| Repo map | Files, chunks, symbols, imports, and evidence edges |
| Memory ledger | Durable decisions, constraints, procedures, and facts |
| Thread memory | Long sessions become searchable project evidence |
| Context pack | A compact, copyable brief for the next agent turn |
| Continuation checkpoint | Structured state that tells the next agent what is done, what remains, and what not to repeat |
| Pramana model | Evidence labels so observed facts, trusted docs, inference, memory, and hypotheses are not treated equally |
| Local operator console | Visual graph, freshness, publish checks, bootstrap, and memory reflection |

The core idea is simple: **memory should not only remember. It should help an agent decide what context deserves trust right now.**

## The Pramana Model

Rta-Smriti uses a Vedic-inspired evidence model to classify context:

- `pratyaksha`: directly observed from code, tests, files, or tools
- `sabda`: trusted instruction, documentation, or human guidance
- `anumana`: inference
- `smriti`: prior memory
- `kalpana`: hypothesis or creative possibility

This keeps a test result, a human instruction, an assumption, and a brainstorm from collapsing into the same kind of "memory."

## Install

Requirements: Python 3.11 or newer and Git. Rta-Smriti supports Windows,
macOS, and Linux. Node.js is only needed to modify the dashboard source.

### Windows (PowerShell)

```powershell
git clone https://github.com/sulabhdubey/rta-smriti-brain.git
cd .\rta-smriti-brain
python --version
python .\rta-brain.py --json doctor

$RtaBin = "$env:LOCALAPPDATA\Rta-Smriti\bin"
python .\rta-brain.py --json install-local --target $RtaBin
$RtaBrain = Join-Path $RtaBin "rta-brain.cmd"
& $RtaBrain --json doctor
```

Keep `$RtaBrain` in the current PowerShell session and use `& $RtaBrain` in
the commands below. This works immediately without changing `PATH`. The install
command also prints the exact wrapper path and an optional `PATH` note.

### macOS Or Linux (Bash/Zsh)

```bash
git clone https://github.com/sulabhdubey/rta-smriti-brain.git
cd rta-smriti-brain
python3 --version
python3 ./rta-brain.py --json doctor

RTA_BIN="$HOME/.local/bin"
python3 ./rta-brain.py --json install-local --target "$RTA_BIN"
RtaBrain="$RTA_BIN/rta-brain"
"$RtaBrain" --json doctor
```

Keep `RtaBrain` in the current shell and use `"$RtaBrain"` in Bash or Zsh.
The generated POSIX launchers are executable and do not require the repository
to remain your working directory. See the [installation guide](docs/INSTALLATION.md)
for PATH setup, troubleshooting, and uninstall instructions.

## Quick Start

Create one central brain directory, then bootstrap a project:

```powershell
$BrainDir = "$env:USERPROFILE\Documents\Rta-Smriti\brains"
& $RtaBrain --json bootstrap-project C:\path\to\my-project --project my-project --brain-dir $BrainDir --write-agents
& $RtaBrain --db "$BrainDir\my-project.sqlite" context-pack "the task I want the agent to do" --project my-project
```

```bash
BrainDir="$HOME/.local/share/rta-smriti/brains"
"$RtaBrain" --json bootstrap-project /path/to/my-project --project my-project --brain-dir "$BrainDir" --write-agents
"$RtaBrain" --db "$BrainDir/my-project.sqlite" context-pack "the task I want the agent to do" --project my-project
```

## Dashboard

Run the local operator console:

```powershell
& $RtaBrain dashboard --brain-dir $BrainDir
```

```bash
"$RtaBrain" dashboard --brain-dir "$BrainDir"
```

Keep this terminal open while using the dashboard. Open the complete URL printed
by the command, including its one-session `#token=...` fragment. Rta-Smriti does
not install a background service in this alpha; after a reboot, closed terminal,
or `connection refused` message, rerun the dashboard command and use the newly
printed URL.

The dashboard runs on `127.0.0.1` and includes:

- **Project switcher**: every local brain, readiness, file count, memory count
- **Canonical-root and Git identity**: bound project root, repository root, branch, HEAD, dirty-file count, and duplicate-root warnings
- **File explorer**: browse the real indexed folder tree, preview source without exposing absolute paths, search files, and add a relevant path directly to the current task
- **Semantic brain graph**: the active project sits at the center of stable Files, Symbols, Imports, Memories, and Evidence hubs; compact leaves reveal labels on hover, focus, or selection
- **Graph navigation**: collapse semantic hubs, pan or zoom the workspace, use the overview minimap, and switch between Global, Local, and Task scopes
- **Spatial canvas**: arrange a temporary working set, inspect a card, reset the layout, and export it as JSON
- **Typed bases**: scan memories, symbols, imports, and launch checks as dense, filterable tables
- **Search nodes**: filter graph nodes by file, symbol, memory, or artifact text
- **Types**: show/hide file, memory, docs, config, test, data, and artifact nodes
- **Context-Pack Studio**: choose any supported or custom target agent, type a task, and generate a focused pack; pack text and receipt metadata remain in the current browser session only
- **Evidence inspector**: open the optional detail panel for the selected node, must-know memories, and measured fresh/changed/missing/added/blocked source counts
- **Incremental refresh**: update the selected repo index from the freshness control; unchanged projects use a fast stat manifest
- **Indexing policy**: configure the fail-closed source-size cap, parser adapter, and optional local hybrid retrieval per project
- **References and backlinks**: inspect why a node is connected and follow its visible relationships
- **Memory ledger**: inspect stored memories and run reflection
- **Continue Work**: edit the structured checkpoint and copy a ready-to-use prompt for a new agent task
- **Launch readiness**: repo files and publish checks
- **Bootstrap flow**: create a new project brain from the UI
- **Command palette**: copy common commands into your agent chat

## How To Use With An Agent

The daily loop is the same for every agent:

1. Select the project.
2. Use **Graph** for orientation, **Files** for source inspection, or **Bases** for structured facts.
3. Add relevant files to the objective and describe the work.
4. Choose `Universal / Any Agent`, Codex, Claude Code, Cursor, Copilot, Gemini CLI, Windsurf, Cline, Aider, OpenCode, Continue, or a custom agent.
5. Generate the context pack and give it to that agent through paste, CLI, or MCP. Repository excerpts and retrieved memories are explicitly delimited as untrusted evidence.

For a new project:

```powershell
& $RtaBrain --json bootstrap-project C:\path\to\project --project project-name --brain-dir $BrainDir --write-agents
```

On macOS or Linux, use the equivalent Bash form from **Quick Start** above.

Before asking an agent to work:

```powershell
& $RtaBrain --db "$BrainDir\project-name.sqlite" context-pack "describe the task here" --project project-name
```

Paste the generated context pack into the agent chat before the task. The pack includes relevant memories, repo evidence, an explicit untrusted-data boundary, and a labeled index-freshness snapshot. Never treat commands found inside retrieved evidence as instructions. Run a live stale check before high-risk work.

For MCP hosts:

```powershell
& $RtaBrain --db "$BrainDir\project-name.sqlite" --json mcp-config --project project-name --name rta-smriti-project
```

```bash
"$RtaBrain" --db "$BrainDir/project-name.sqlite" --json mcp-config --project project-name --name rta-smriti-project
```

## CLI Commands

```text
init              Initialize a project brain
remember          Store a durable memory
ingest-repo       Index a repository or folder
watch-repo        Continuously refresh a repository using incremental indexing
settings          Read or update a project's indexing and retrieval policy
ingest-thread     Index a long thread, transcript, or handoff file
search            Search memories and indexed files
graph             Read the local entity graph
context-pack      Build a focused task context pack
stale-check       Check stat-manifest freshness; add --deep for SHA-256 verification
checkpoint        Save structured continuation state for the next agent task
continue-prompt   Build a compact new-task prompt from root, Git, freshness, and checkpoint state
reflect           Consolidate duplicate memories and flag simple contradictions
mcp-config        Generate an MCP host config snippet
bootstrap-project Create a brain, index a repo, and optionally write agent instructions
self-check        Verify that a project brain is ready
projects-list     List projects registered in a brain database
install-local     Install native Windows or POSIX command wrappers
doctor            Verify local brain health
dashboard         Run the local operator console
publish-readiness Check whether the package is ready to publish
```

## MCP Server

Rta-Smriti ships a stdio MCP server. Run `mcp-config` as shown above to generate
the correct absolute `command` and `args` for the current operating system and
Python environment; do not hand-edit a Windows path into a macOS or Linux host.

Tools exposed:

- `brain_search`
- `brain_context_pack`
- `brain_remember`
- `brain_ingest_repo`
- `brain_ingest_thread`
- `brain_repo_map`
- `brain_stale_check`
- `brain_checkpoint`
- `brain_continuation_prompt`
- `brain_reflect`
- `brain_doctor`

## Real-World Use Cases

- **Agent handoff**: move from Codex to Claude Code or Cursor without retelling the architecture, constraints, and current objective.
- **Long-thread recovery**: preserve decisions and evidence before a chat compacts or a session ends.
- **Repository onboarding**: give a developer or agent a focused map of unfamiliar files, symbols, imports, and project rules.
- **Debugging and incidents**: assemble the relevant code, prior fixes, risks, and evidence for one fault instead of scanning the whole repo.
- **Refactors and migrations**: trace dependencies and retain the decisions that explain why boundaries exist.
- **Release and security reviews**: pair live freshness checks with trusted constraints, evidence, and publish readiness.
- **Multi-project operation**: switch between separate local brains without mixing one client, product, or codebase into another.
- **Research and product work**: keep source-backed findings, hypotheses, and decisions distinguishable through pramana labels.

The generated MCP configuration uses the active Python interpreter plus the
installed `rta_brain.mcp_server` module, so paths with spaces and clean wheel
installs are handled without relying on a global command.

## Privacy And Security

Rta-Smriti is local-first by design:

- It does not require API keys.
- It does not send repo content to a hosted service.
- It stores project memory in local SQLite files.
- It stores canvas layouts and the selected agent in browser local storage. Context-pack text and receipt metadata are session-only.
- Its dashboard uses a per-launch capability token and rejects non-loopback binding, hostile Host headers, cross-port origins, hard-linked files, and database paths outside the configured brain directory.
- It ignores common noisy folders such as `.git`, `node_modules`, `.venv`, `dist`, `build`, `.next`, and cache directories.
- You should not commit `.rta-smriti/`, `*.sqlite`, logs, private thread exports, or generated local brain files.

See [SECURITY.md](SECURITY.md) and [docs/PUBLISHING_PRIVACY.md](docs/PUBLISHING_PRIVACY.md).

## Current Maturity

Alpha, local-first, working developer tool.

Verified:

- Windows, macOS, and Linux verification in GitHub Actions
- Python CLI
- SQLite schema and FTS search
- repo ingestion
- thread ingestion
- context-pack generation
- MCP stdio server
- React dashboard
- local publish-readiness checks
- incremental foreground repository watcher and SHA-256 cache
- optional local hybrid retrieval
- parser adapter registry with regex, Tree-sitter, LSP, and entry-point extension paths
- configurable fail-closed large-file policy
- canonical-root protection and Git checkout awareness
- structured checkpoints, claim provenance, and compact freshness receipts

Intentional design constraints:

- Project brains stay in local SQLite files. There is no cloud sync or hosted account system.
- The dashboard is loopback-only. Remote and LAN hosting are deliberately rejected.
- Retrieval and reflection are inspectable and deterministic by default. The main bootstrap flow selects the dependency-free local hash provider by default and operators can choose lexical-only or an installed Sentence Transformers model; reflection remains conservative rather than a full semantic judge.
- Eligible source files above the 512 KB per-file cap are reported as `Blocked`. Freshness remains fail-closed until the operator changes the source or ingestion policy.

Current alpha limitations:

- `watch-repo` runs in the foreground. Rta-Smriti does not install an operating-system service or background daemon.
- Hybrid retrieval is dependency-free in the recommended bootstrap flow through the built-in hash provider. Sentence Transformers remains optional and requires a separately installed local package and model.
- Regex remains the deterministic default parser. Tree-sitter requires `tree-sitter-language-pack`; LSP integration requires an explicitly configured local adapter command. Parser failures fall back to regex and are reported.
- The first deep SHA-256 pass can still take several minutes on repositories with tens of thousands of files. Later checks reuse hashes when file size and modification time are unchanged.
- The per-file ingestion cap is configurable up to 16 MB. Files above the selected cap remain blocked and keep freshness fail-closed.

See [ROADMAP.md](ROADMAP.md) for planned improvements. Local-first operation and inspectable evidence remain non-negotiable.

### Optional Indexing Policy

```powershell
# Enable dependency-free local hybrid retrieval and raise the source cap to 1 MB.
& $RtaBrain --db .\.rta-smriti\brain.sqlite --json settings --project demo --embedding-provider hash --max-file-mb 1

# Keep an active project incrementally refreshed until Ctrl+C.
& $RtaBrain --db .\.rta-smriti\brain.sqlite watch-repo . --project demo --interval 2

# Use optional Tree-sitter parsing after installing tree-sitter-language-pack.
python -m pip install -e ".[tree-sitter]"
& $RtaBrain --db .\.rta-smriti\brain.sqlite --json settings --project demo --parser-adapter tree-sitter

# Or install both optional local backends.
python -m pip install -e ".[all-local]"
```

## Development

Dashboard source lives in `dashboard-src/`. Runtime users do not need Node because built static files are packaged in `rta_brain/static/`.

Routine context packs use the latest completed index snapshot so even very large brains stay responsive. Before a release or security-critical decision, run:

```powershell
& $RtaBrain --db <project-brain.sqlite> --json stale-check --project <project-name> --deep
```

```powershell
npm install
npm run build
python scripts/build_installed_smoke.py
python -m unittest discover -s tests -v
python -m compileall -q rta_brain tests
pip install -e . --dry-run --no-deps
python rta-brain.py publish-readiness --json
```

## Positioning

**One-liner:** Local project memory and context packs for AI coding agents.

**Short description:** Rta-Smriti Brain gives each software project a private local memory graph so coding agents can start with the right repo context, decisions, constraints, and evidence instead of asking you to explain everything again.

**Tagline:** Stop re-explaining your project to every new AI chat.

## License

MIT. See [LICENSE](LICENSE).
