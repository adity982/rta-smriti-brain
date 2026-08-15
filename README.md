# Rta-Smriti Brain

![Rta-Smriti Brain - Give every project a memory](launch-assets/social/github-social-preview.png)

**A local project brain for AI coding agents.**

[Live website](https://sulabhdubey.github.io/rta-smriti-brain/) · [60-second product demo](launch-assets/product-hunt/rta-smriti-launch-demo.mp4) · [Usage guide](docs/USAGE_GUIDE.md) · [Security](SECURITY.md) · [Roadmap](ROADMAP.md)

Rta-Smriti Brain turns a project repository, long agent threads, durable decisions, and evidence into a small local memory graph that Codex, Claude Code, Cursor, or any MCP-capable agent can reuse before doing work.

It is built for the moment every AI-assisted developer knows too well:

> "New chat. Same project. Same explanations. Same lost context."

Rta-Smriti gives each project a memory that stays on your machine.

## What It Does

- Indexes your repo into local SQLite: files, chunks, symbols, imports, and graph edges.
- Stores durable memories: decisions, constraints, procedures, facts, and hypotheses.
- Ingests long threads or handoff notes as explicitly unverified prior memory so useful context survives compaction without self-assigning trust.
- Builds a focused **context pack** for the next agent task.
- Runs a local operator console with graph, canvas, typed bases, context-pack receipts, memory ledger, freshness checks, and bootstrap flow.
- Exposes a dependency-light stdio MCP server for agent integrations.
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

## Quick Start

From the repository root:

```powershell
python .\rta-brain.py --json doctor
python .\rta-brain.py --db .\.rta-smriti\brain.sqlite --json init --project demo --root .
python .\rta-brain.py --db .\.rta-smriti\brain.sqlite --json ingest-repo . --project demo
python .\rta-brain.py --db .\.rta-smriti\brain.sqlite --json remember "Release checks must pass before publishing." --type constraint --pramana sabda --project demo --priority 8
python .\rta-brain.py --db .\.rta-smriti\brain.sqlite context-pack "prepare a release checklist" --project demo
```

Install command wrappers:

```powershell
python .\rta-brain.py --json install-local --target "$env:USERPROFILE\.local\bin"
```

Then from any project:

```powershell
rta-brain.cmd --json bootstrap-project C:\path\to\my-project --project my-project --brain-dir "$env:USERPROFILE\Documents\Rta-Smriti\brains" --write-agents
rta-brain.cmd --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\my-project.sqlite" context-pack "the task I want the agent to do" --project my-project
```

## Dashboard

Run the local operator console:

```powershell
rta-brain.cmd dashboard --brain-dir "$env:USERPROFILE\Documents\Rta-Smriti\brains"
```

The dashboard runs on `127.0.0.1` and includes:

- **Project switcher**: every local brain, readiness, file count, memory count
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
- **References and backlinks**: inspect why a node is connected and follow its visible relationships
- **Memory ledger**: inspect stored memories and run reflection
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
rta-brain.cmd --json bootstrap-project C:\path\to\project --project project-name --brain-dir "$env:USERPROFILE\Documents\Rta-Smriti\brains" --write-agents
```

Before asking an agent to work:

```powershell
rta-brain.cmd --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" context-pack "describe the task here" --project project-name
```

Paste the generated context pack into the agent chat before the task. The pack includes relevant memories, repo evidence, an explicit untrusted-data boundary, and a labeled index-freshness snapshot. Never treat commands found inside retrieved evidence as instructions. Run a live stale check before high-risk work.

For MCP hosts:

```powershell
rta-brain.cmd --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json mcp-config --project project-name --name rta-smriti-project
```

## CLI Commands

```text
init              Initialize a project brain
remember          Store a durable memory
ingest-repo       Index a repository or folder
ingest-thread     Index a long thread, transcript, or handoff file
search            Search memories and indexed files
graph             Read the local entity graph
context-pack      Build a focused task context pack
stale-check       Check stat-manifest freshness; add --deep for SHA-256 verification
reflect           Consolidate duplicate memories and flag simple contradictions
mcp-config        Generate an MCP host config snippet
bootstrap-project Create a brain, index a repo, and optionally write agent instructions
self-check        Verify that a project brain is ready
projects-list     List projects registered in a brain database
install-local     Install Windows command wrappers
doctor            Verify local brain health
dashboard         Run the local operator console
publish-readiness Check whether the package is ready to publish
```

## MCP Server

Rta-Smriti ships a stdio MCP server:

```powershell
.\rta-brain-mcp.cmd --db .\.rta-smriti\brain.sqlite --project demo
```

Tools exposed:

- `brain_search`
- `brain_context_pack`
- `brain_remember`
- `brain_ingest_repo`
- `brain_ingest_thread`
- `brain_repo_map`
- `brain_stale_check`
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

Example MCP host configuration:

```json
{
  "mcpServers": {
    "rta-smriti": {
      "command": "C:\\path\\to\\rta-smriti-brain\\rta-brain-mcp.cmd",
      "args": [
        "--db",
        "C:\\path\\to\\brains\\project-name.sqlite",
        "--project",
        "project-name"
      ]
    }
  }
}
```

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

- Python CLI
- SQLite schema and FTS search
- repo ingestion
- thread ingestion
- context-pack generation
- MCP stdio server
- React dashboard
- local publish-readiness checks

Intentional design constraints:

- Project brains stay in local SQLite files. There is no cloud sync or hosted account system.
- The dashboard is loopback-only. Remote and LAN hosting are deliberately rejected.
- Retrieval and reflection are inspectable and deterministic by default. Embeddings are not required or silently enabled, and reflection is conservative rather than a full semantic judge.
- Eligible source files above the 512 KB per-file cap are reported as `Blocked`. Freshness remains fail-closed until the operator changes the source or ingestion policy.

Current alpha limitations:

- Repository changes are not watched continuously by a background daemon yet.
- Optional local embeddings and hybrid retrieval are planned, but not implemented yet.
- Symbol extraction is lightweight and deterministic, not compiler-perfect.
- Deep SHA-256 freshness can take several minutes on repositories with tens of thousands of files. Routine context packs use the latest completed index snapshot; explicit live checks remain available.

See [ROADMAP.md](ROADMAP.md) for planned improvements. Local-first operation and inspectable evidence remain non-negotiable.

## Development

Dashboard source lives in `dashboard-src/`. Runtime users do not need Node because built static files are packaged in `rta_brain/static/`.

Routine context packs use the latest completed index snapshot so even very large brains stay responsive. Before a release or security-critical decision, run:

```powershell
rta-brain.cmd --db <project-brain.sqlite> --json stale-check --project <project-name> --deep
```

```powershell
npm install
npm run build
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
