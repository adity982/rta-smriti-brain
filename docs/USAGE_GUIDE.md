# Rta-Smriti Brain Usage Guide

This guide explains how to use Rta-Smriti Brain across multiple local software projects.

## The Simple Idea

Each project gets its own local brain database.

That brain remembers:

- important decisions
- project rules
- repo files and symbols
- long thread handoffs
- stale or changed files
- context that the next AI agent should know

When you start a new Codex, Claude Code, Cursor, or other agent chat, ask Rta-Smriti for a context pack and paste it into the chat before the task.

## Install The Local Launcher

From a cloned Rta-Smriti repository, run the command for your operating system.

Windows PowerShell:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install .
$RtaBrain = Join-Path $PWD ".venv\Scripts\rta-brain.exe"
& $RtaBrain --json doctor
```

Use `& $RtaBrain` for the examples in this guide. Pip generates the launcher
from package metadata, so no source wrapper or global `PATH` is required.

macOS or Linux:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install .
RtaBrain="$PWD/.venv/bin/rta-brain"
"$RtaBrain" --json doctor
```

Use `"$RtaBrain"` for the Bash/Zsh examples. See the complete
[installation guide](INSTALLATION.md) for prerequisites, PATH setup,
troubleshooting, and uninstall instructions.

## Recommended Folder Layout

Use one central folder for all project brains:

```powershell
$env:USERPROFILE\Documents\Rta-Smriti\brains
```

```bash
$HOME/.local/share/rta-smriti/brains
```

Each project brain becomes one SQLite file:

```text
brains/
  app-one.sqlite
  backend-service.sqlite
  docs-site.sqlite
```

Do not commit this folder to GitHub.

## Bootstrap A Project

Run once per project:

```powershell
& $RtaBrain --json bootstrap-project C:\path\to\project --project project-name --brain-dir "$env:USERPROFILE\Documents\Rta-Smriti\brains" --write-agents
```

```bash
BrainDir="$HOME/.local/share/rta-smriti/brains"
"$RtaBrain" --json bootstrap-project /path/to/project --project project-name --brain-dir "$BrainDir" --write-agents
```

This creates:

- a SQLite brain database
- indexed repo evidence
- a project record
- optional `AGENTS.rta-smriti.md` instructions in that project

## Check A Project Brain

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json self-check --project project-name --check-files
```

```bash
"$RtaBrain" --db "$BrainDir/project-name.sqlite" --json self-check --project project-name --check-files
```

Look for:

- `ready: true`
- file counts greater than zero
- memories greater than zero, if you have added decisions
- low or zero stale files

## Generate Context Before A Task

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" context-pack "describe the task here" --project project-name --max-tokens 4000
```

```bash
"$RtaBrain" --db "$BrainDir/project-name.sqlite" context-pack "describe the task here" --project project-name --max-tokens 4000
```

Paste the output into the agent chat, then ask the agent to do the task.

Good task examples:

```text
fix the checkout validation bug
prepare this repo for GitHub launch
review auth boundaries before changing user roles
continue the release hardening work from the previous thread
```

## Use The Dashboard

Run:

```powershell
& $RtaBrain dashboard --brain-dir "$env:USERPROFILE\Documents\Rta-Smriti\brains"
```

```bash
"$RtaBrain" dashboard --brain-dir "$BrainDir"
```

Open the URL printed in the terminal.

Keep the terminal open while the dashboard is in use. The complete printed URL,
including `#token=...`, authorizes that browser session. If the browser later
reports `connection refused`, rerun the dashboard command and open its new URL.
Repository sync is a separate per-project background process when enabled; the
dashboard and watcher are never registered as login or privileged system services.

### The Daily Five-Step Loop

1. Open **Projects** and select the project you are working on.
2. Orient yourself in **Graph**, then inspect exact source in **Files** or structured facts in **Bases**.
3. In **Context-Pack Studio**, describe one concrete task. Use `Add to Task` in a file preview when a path matters.
4. Choose the target agent. `Universal / Any Agent` is the safest default; named and custom agents add a clear handoff label to the pack and receipt.
5. Generate the pack, copy it, and place it at the start of the agent chat. MCP-capable hosts can call the brain tools directly instead.

Before ending a meaningful session, open **Continue Work** and record the objective, verified evidence, remaining gaps, safest next action, and exploration that should not be repeated. Save the checkpoint, then use **Copy New Task Prompt** when opening the next agent task.

Graph is the map, Files is the source reader, Canvas is the working board, Bases is the structured database, and the Context-Pack Studio is the handoff point.

### What The Dashboard Shows

**Projects**

Every brain found in your brain folder. The switcher shows readiness, file count, memory count, Git branch and HEAD, and the project path without mixing data between projects. A yellow state warns when the same project name is bound to multiple folders; verify the canonical checkout before using that brain.

**Files**

The actual indexed project tree. Open folders, search by relative path, preview indexed source, copy a safe relative path, or add that file to the current task. Absolute local paths are not shown in previews.

**Brain Graph**

A semantic map of the active project. The center is the project brain; stable hubs group Files, Symbols, Imports, Memories, and Evidence. Hover or focus a compact leaf to read it, click a hub to collapse or expand it, and use pan, zoom, reset, or the minimap to navigate. Brighter links are repository evidence; faint dashed links only explain the visual grouping. Switch between Global, Local, and Task scopes to change the working set.

**Canvas**

A draggable working board for arranging the current evidence set. Double-click a card to inspect it, reset the layout when needed, and export the arrangement as JSON.

**Bases, Symbols, Imports, And Memories**

Filterable table views for facts that are easier to scan as rows than as a graph. The dedicated left-navigation items open the relevant base directly.

**Search Nodes**

Searches graph nodes so you can quickly find a file, memory, symbol, or generated context pack.

**Types**

Filters the graph by node type.

**Settings**

Controls the active project's indexing policy. Auto parsing uses an installed Tree-sitter grammar when supported and safely falls back to built-in regex. You can also select regex explicitly, configure an LSP bridge, change hybrid retrieval, or adjust the fail-closed source cap. External providers are never installed automatically.

**Context-Pack Studio**

The main daily workflow. Choose `Universal / Any Agent`, a named agent, or a custom agent. Select a 2K, 4K, 8K, or 16K context budget, type the task, click `Generate Context Pack`, then copy the pack into the agent chat. Direct evidence is considered before lower-trust historical memory, and omitted material is declared. Each generation creates privacy-safe receipt metadata; the full pack stays available only in the current browser session.

**Evidence Inspector**

Open the detail-panel button in the graph toolbar to see what is selected, must-know memories, measured freshness counts, canonical root, Git branch, HEAD, dirty-file count, repo tree hints, and publish readiness. A `Blocked` freshness count means an eligible source could not be safely inspected, such as an oversized or symlinked source. Use the refresh action to incrementally update the selected repo index.

**References**

Shows visible connections and backlinks for the selected graph node.

**Memory Ledger**

Shows remembered decisions, their verification provenance when recorded, and lets you run reflection to suppress duplicate memories or flag simple contradictions.

**Continue Work**

Stores objective, verified evidence, remaining gaps, next action, and prohibited repetition as structured SQLite fields. The newest checkpoint leads future context packs and the one-click new-task prompt. Every save carries an optimistic version, so a stale agent is warned instead of overwriting newer state.

**Launch Readiness**

Shows what the package needs before publishing.

**Bootstrap Brain**

Creates a new project brain from the UI.

**Command Palette**

Copies common commands so you do not have to remember syntax.

## Real-World Use Cases

**Continue after context compaction**

Ingest a long thread or handoff, then generate a focused pack for the next chat. The next agent receives decisions and evidence without receiving the entire transcript.

**Switch agents without starting over**

Generate one universal pack or label it for Codex, Claude Code, Cursor, Copilot, Gemini CLI, or another agent. The brain stays agent-neutral; the target is handoff metadata, not a lock-in.

**Understand an unfamiliar repository**

Use Graph to see structure, Files to inspect source, Symbols and Imports to scan implementation boundaries, and Bases to compare structured records.

**Debug a specific problem**

Name the failure in the objective, add the relevant files, and generate a narrow pack containing matching code evidence plus prior constraints and fixes.

**Prepare a release or security review**

Run live or deep freshness checks, inspect evidence and launch readiness, and hand the resulting context to the reviewing agent.

**Operate several products privately**

Keep one SQLite brain per project. The dashboard switches between them while all repo content, memories, canvas layouts, and receipts remain local.

## Cross-Project Acceptance Check

You do not need to run a test before normal daily use. Before publishing the tool or after changing its indexing code, validate at least one tiny, one medium, and one large repository:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json self-check --project project-name --check-files
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" context-pack "explain the architecture and safest next step" --project project-name
```

Confirm that the project is ready, Files opens, a preview can be added to the task, the selected target agent appears on the receipt, and the generated pack contains only that project's evidence.

## Add A Memory Manually

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" remember "Payments must fail closed when verification is missing." --project project-name --type constraint --pramana sabda --priority 9
```

Use memory types like:

- `decision`
- `constraint`
- `procedure`
- `fact`
- `risk`
- `idea`

Use pramana labels:

- `pratyaksha`: directly observed
- `sabda`: trusted instruction or docs
- `anumana`: inference
- `smriti`: prior memory
- `kalpana`: hypothesis

## Ingest A Long Thread Or Handoff

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json ingest-thread C:\path\to\handoff.md --project project-name --title "release handoff"
```

Use this after a long agent session so the next chat can recover the useful decisions and evidence.

## Refresh Repo Evidence

After significant code changes:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json ingest-repo C:\path\to\project --project project-name
```

Then:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json stale-check --project project-name
```

Use `--deep` for SHA-256 freshness with stat-keyed cache reuse. Fresh file rows are summarized by default so the receipt stays compact; add `--details --detail-limit 100` only when individual fresh rows are needed. Use `ingest-repo --force` when you need to re-read and re-index every eligible source regardless of cached metadata.

## Save A Continuation Checkpoint

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json checkpoint --project project-name --objective "Finish root protection" --verified-evidence "Regression test passes" --remaining-gaps "Dashboard review" --next-action "Run UI smoke" --prohibited-repetition "Do not rescan unrelated folders"
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" continue-prompt --project project-name
```

The equivalent macOS/Linux commands use `"$RtaBrain"` and `$BrainDir/project-name.sqlite` as shown earlier.

## Attach Claim Provenance

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json remember "Checkout verification fails closed." --project project-name --type evidence --pramana pratyaksha --source-path tests/test_checkout.py --source-hash abc123 --verification-command "python -m unittest tests.test_checkout" --verification-status verified
```

Verification status can be `unverified`, `verified`, `failed`, or `stale`. Rta-Smriti records the verification timestamp automatically unless one is supplied.

Keep a repository refreshed while you work:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" watch-repo C:\path\to\project --project project-name --interval 2
```

This watcher stays in the foreground and stops cleanly with `Ctrl+C`. For managed background sync, use **Settings > Repository sync** in the dashboard or:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" watcher start C:\path\to\project --project project-name --interval 2
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json watcher status --project project-name
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" watcher stop --project project-name
```

The managed worker survives terminal and dashboard closure. It is not a privileged operating-system service, never auto-starts at login, and must be restarted after a reboot. Install `.[watcher]` for event-driven updates; otherwise the same command uses portable polling.

## Configure Retrieval And Parsing

The recommended bootstrap defaults are automatic Tree-sitter-with-regex-fallback parsing, FTS5 plus dependency-free hash hybrid retrieval, and a 512 KB source cap. A raw `init` remains lexical-only until configured. Read the active policy:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json settings --project project-name
```

Enable the dependency-free local hash provider and a 1 MB source cap:

```powershell
& $RtaBrain --db "$env:USERPROFILE\Documents\Rta-Smriti\brains\project-name.sqlite" --json settings --project project-name --embedding-provider hash --max-file-mb 1
```

Changing an indexing policy invalidates the fast manifest. Run `ingest-repo` or use the dashboard refresh action to rebuild affected records. Sources above the selected cap remain visibly blocked.

Install optional local backends from the repository only when you need them:

```powershell
python -m pip install -e ".[tree-sitter]"
python -m pip install -e ".[embeddings]"
```

## What Not To Publish

Never commit:

- `*.sqlite`
- `.rta-smriti/`
- private thread exports
- local screenshots with private project names
- logs containing local paths
- generated brain folders
- credentials or API keys

The public GitHub repo should contain only the tool, docs, tests, and demo-safe assets.
