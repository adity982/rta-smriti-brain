# Rta-Smriti Brain Launch Kit

## Product Name

Rta-Smriti Brain

## Tagline

Stop re-explaining your project to every new AI chat.

## One-Liner

Local project memory and context packs for AI coding agents.

## Short Description

Rta-Smriti Brain gives every software project a private local memory graph. It indexes your repo, remembers durable decisions, ingests long agent threads, and generates focused context packs that Codex, Claude Code, Cursor, or any MCP-capable agent can reuse before doing work.

## Simple Explanation

AI coding agents are powerful, but every new chat starts with amnesia. You explain the same architecture, decisions, bugs, and release rules again and again.

Rta-Smriti Brain fixes that by giving each project a local brain. It stores what matters, keeps it searchable, shows it as a graph, and produces a short context pack for the next agent task.

Your project context stays on your machine.

## Maker Comment

I built Rta-Smriti Brain because long AI coding sessions kept losing the most important thing: project memory.

The tool is local-first. It uses SQLite, a small CLI, a stdio MCP server, and a React operator console. You can bootstrap a project, index its repo, store decisions, ingest long thread handoffs, and generate a context pack before the next agent chat.

The unique part is the evidence model. Rta-Smriti uses `pratyaksha`, `sabda`, `anumana`, `smriti`, and `kalpana` labels so directly observed facts, trusted instructions, inferences, memories, and hypotheses do not all get treated as the same kind of context.

This is an alpha developer tool, but it is already useful if you work across multiple projects and hate re-explaining the same context to every new AI session.

## Moats

### 1. Local-First Trust

No hosted database. No account system. No telemetry. Project memory is stored in local SQLite files.

### 2. Repo + Memory + Thread Fusion

Most tools focus on one layer: notes, repo search, or chat memory. Rta-Smriti combines repo evidence, durable decisions, long-thread handoffs, and task focused context packs.

### 3. Evidence-Aware Memory

The pramana model labels the kind of evidence behind a memory. A test result, a human instruction, an inference, and a brainstorm are not treated as equal.

### 4. Agent-Ready Output

The context pack is not a notebook page. It is shaped for the next coding-agent turn: concise, relevant, copyable, and warning-aware.

### 5. Visual Operator Console

The dashboard is not a landing page. It is a real local operator console with project switching, graph search, memory ledger, context-pack studio, bootstrap flow, and publish readiness.

### 6. MCP-Compatible Path

The stdio MCP server makes the same memory usable by compatible agent hosts.

## Feature List

- Local SQLite memory store
- Repository ingestion
- Symbol and import indexing
- Long-thread and handoff ingestion
- Durable memory ledger
- Pramana evidence labels
- Context-pack generation
- Stale-file checks
- Reflection for duplicates and simple contradictions
- Stdio MCP server
- React dashboard/operator console
- Project switcher
- Interactive graph canvas
- Node search and type filters
- Bootstrap flow
- GitHub publish readiness checker

## Comparison Positioning

| Category | Typical behavior | Rta-Smriti difference |
| --- | --- | --- |
| Plain second brain | Stores notes | Stores repo evidence, decisions, handoffs, and graph context |
| Code indexer | Searches files | Adds durable memory and task packs |
| Vector memory | Recalls similar text | Adds evidence labels, freshness, and deterministic local checks |
| Agent chat memory | Lives inside one tool | Works as a local project layer outside the chat |
| MCP memory server | Exposes tools | Also includes CLI, dashboard, bootstrap flow, and publish checks |

## Product Hunt Fields

Name:

```text
Rta-Smriti Brain
```

Tagline:

```text
Local project memory and context packs for AI coding agents.
```

Description:

```text
Give each software project a private local brain. Rta-Smriti indexes your repo, remembers decisions, ingests long agent threads, and generates focused context packs for Codex, Claude Code, Cursor, and MCP-capable agents.
```

Topics:

```text
Developer Tools, Artificial Intelligence, Open Source, Productivity, GitHub
```

First comment:

```text
AI coding agents are getting stronger, but most project memory still disappears when a chat gets long or a new session starts.

Rta-Smriti Brain is a local-first project memory layer. It stores repo evidence, durable decisions, long-thread handoffs, and task focused context packs in SQLite. The dashboard lets you switch projects, inspect a graph, search nodes, reflect memories, and bootstrap new project brains.

The product is alpha, open source, and built for developers who work across multiple AI-assisted projects.
```

## Launch Assets Needed

- GitHub repository with clean README
- MIT license
- Demo screenshot using only sample project data
- 60-90 second demo video
- Product Hunt gallery images
- Short install GIF
- Public issue templates
- Release notes for `v0.3.0-alpha`

## Demo Script

1. Bootstrap a demo project brain.
2. Open the dashboard.
3. Switch between demo projects.
4. Search the graph for a file or memory.
5. Generate a context pack for a task.
6. Copy the pack into an AI agent chat.
7. Show that the memory never left the local machine.

## Launch-Day Message

```text
I launched Rta-Smriti Brain today.

It is a local project memory layer for AI coding agents. It gives each repo a private brain, indexes code and long threads, remembers durable decisions, and generates focused context packs so every new agent chat starts with the right context.

GitHub: <repo-url>
Product Hunt: <product-hunt-url>
```
