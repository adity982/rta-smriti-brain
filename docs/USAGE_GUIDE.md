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

## Recommended Folder Layout

Use one central folder for all project brains:

```powershell
%USERPROFILE%\Documents\Rta-Smriti\brains
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
rta-brain.cmd --json bootstrap-project C:\path\to\project --project project-name --brain-dir "%USERPROFILE%\Documents\Rta-Smriti\brains" --write-agents
```

This creates:

- a SQLite brain database
- indexed repo evidence
- a project record
- optional `AGENTS.rta-smriti.md` instructions in that project

## Check A Project Brain

```powershell
rta-brain.cmd --db "%USERPROFILE%\Documents\Rta-Smriti\brains\project-name.sqlite" --json self-check --project project-name --check-files
```

Look for:

- `ready: true`
- file counts greater than zero
- memories greater than zero, if you have added decisions
- low or zero stale files

## Generate Context Before A Task

```powershell
rta-brain.cmd --db "%USERPROFILE%\Documents\Rta-Smriti\brains\project-name.sqlite" context-pack "describe the task here" --project project-name
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
rta-brain.cmd dashboard --brain-dir "%USERPROFILE%\Documents\Rta-Smriti\brains"
```

Open the URL printed in the terminal.

### What The Dashboard Shows

**Projects**

Every brain found in your brain folder. Each card shows readiness, file count, memory count, and the project path.

**Brain Graph**

A visual map of the active project. The center is the active project brain. Around it are files, symbols, memories, docs, config, tests, data, and generated artifacts.

**Search Nodes**

Searches graph nodes so you can quickly find a file, memory, symbol, or generated context pack.

**Types**

Filters the graph by node type.

**Task Composer**

The main daily workflow. Type the task, click `Generate Context Pack`, then copy the pack into the agent chat.

**Evidence Inspector**

Shows what is selected, must-know memories, freshness, repo tree hints, and publish readiness.

**Memory Ledger**

Shows remembered decisions and lets you run reflection to suppress duplicate memories or flag simple contradictions.

**Launch Readiness**

Shows what the package needs before publishing.

**Bootstrap Brain**

Creates a new project brain from the UI.

**Command Palette**

Copies common commands so you do not have to remember syntax.

## Add A Memory Manually

```powershell
rta-brain.cmd --db "%USERPROFILE%\Documents\Rta-Smriti\brains\project-name.sqlite" remember "Payments must fail closed when verification is missing." --project project-name --type constraint --pramana sabda --priority 9
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
rta-brain.cmd --db "%USERPROFILE%\Documents\Rta-Smriti\brains\project-name.sqlite" --json ingest-thread C:\path\to\handoff.md --project project-name --title "release handoff"
```

Use this after a long agent session so the next chat can recover the useful decisions and evidence.

## Refresh Repo Evidence

After significant code changes:

```powershell
rta-brain.cmd --db "%USERPROFILE%\Documents\Rta-Smriti\brains\project-name.sqlite" --json ingest-repo C:\path\to\project --project project-name
```

Then:

```powershell
rta-brain.cmd --db "%USERPROFILE%\Documents\Rta-Smriti\brains\project-name.sqlite" --json stale-check --project project-name
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
