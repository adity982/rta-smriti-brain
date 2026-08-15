# Maintainer Launch Playbook

This public maintainer guide contains reusable launch copy and release steps.
It is not end-user documentation and does not record private campaign contacts,
credentials, schedules, or unpublished URLs.

## Current Publication State

- Website: https://sulabhdubey.github.io/rta-smriti-brain/
- Repository: https://github.com/sulabhdubey/rta-smriti-brain
- Source on `main`: `0.4.0-alpha`
- Formal `v0.4.0-alpha` tag and GitHub Release: intentionally not created

## Positioning

**Product:** Rta-Smriti Brain

**Tagline:**

```text
Stop re-explaining your project to every new AI chat.
```

**One-liner:**

```text
Local project memory and context packs for AI coding agents.
```

**Simple explanation:**

AI coding agents are powerful, but every new chat starts with amnesia.
Rta-Smriti gives each software project a private local brain. It indexes the
repository, remembers durable decisions, preserves long-session handoffs, and
prepares a focused context pack for the next task. The memory stays on the
operator's machine.

## Product Directory Copy

**Name**

```text
Rta-Smriti Brain
```

**Tagline**

```text
Stop re-explaining your project to every new AI chat.
```

**Description**

```text
Give every software project a private local brain. Rta-Smriti indexes repository structure, remembers durable decisions, preserves long agent-session handoffs, and generates focused context packs for Codex, Claude Code, Cursor, and other agents. SQLite, CLI, MCP, and the visual operator console all run locally with no account, telemetry, or cloud database.
```

**Topics**

```text
Developer Tools, Artificial Intelligence, Open Source, Productivity, GitHub
```

## Maker Comment

```text
AI coding agents are getting stronger, but the project memory around them still disappears when a chat gets long, a session ends, or you switch tools.

I built Rta-Smriti Brain to move that memory out of the chat and into the project. It combines repository structure, durable decisions, long-session handoffs, and task-specific context packs in a local SQLite brain. The operator console lets you inspect the graph, browse indexed files, review memories, check freshness, and prepare context for any agent.

The unusual part is the Pramana evidence model. An observed test result, a trusted human instruction, an inference, a prior memory, and a hypothesis remain different kinds of knowledge instead of becoming one undifferentiated memory blob.

This is an alpha developer release. It is open source and local-first. I would especially value feedback on onboarding, retrieval quality, and integrations with your preferred coding agent.
```

## What Makes It Different

1. **Project memory, not chat memory:** the brain belongs to the repository and survives agents and sessions.
2. **Repo + decisions + handoffs:** structural code evidence and human knowledge live in one inspectable layer.
3. **Evidence-aware recall:** Pramana labels distinguish observation, trusted instruction, inference, memory, and hypothesis.
4. **Task-shaped output:** context packs compile bounded information for one objective instead of dumping the entire brain.
5. **Agent-neutral:** use copy/paste, CLI, project instructions, skills, or stdio MCP.
6. **Local-first trust:** SQLite storage, loopback-only console, no account, no telemetry, no hosted database.
7. **Inspectable operation:** graph, files, Canvas, typed Bases, memory ledger, freshness, receipts, and publish checks are visible to the operator.

## Gallery Order

1. `launch-assets/product-hunt/gallery-01-project-memory.png`
2. `launch-assets/product-hunt/gallery-02-any-agent.png`
3. `launch-assets/product-hunt/gallery-03-evidence.png`
4. `launch-assets/product-hunt/gallery-04-focused-pack.png`
5. Video generated from `launch-video/`

Use `launch-assets/product-hunt/thumbnail-240.png` as the thumbnail.

## Reusable Launch Posts

**LinkedIn / X**

```text
I built Rta-Smriti Brain because every new AI coding chat kept forgetting the project.

It gives each repository a private local brain: repo structure, durable decisions, long-session handoffs, evidence labels, and focused context packs for any coding agent.

Open source. SQLite. CLI + MCP + visual operator console. No account or telemetry.

https://github.com/sulabhdubey/rta-smriti-brain
```

**Show HN**

```text
Show HN: Rta-Smriti Brain - local project memory for AI coding agents

I built an open-source local memory layer that indexes repository structure, durable decisions, and long agent-session handoffs into SQLite, then generates bounded context packs for a concrete task. It includes a CLI, stdio MCP server, and an inspectable React operator console. The evidence model keeps observed facts, trusted instructions, inferences, memories, and hypotheses distinct. I would value feedback on retrieval quality and agent integrations.
```

## Release Sequence

1. Run every command in `docs/RELEASE_VERIFICATION.md` and review the output.
2. Confirm the default branch, repository description, topics, Pages workflow, Discussions, and vulnerability reporting.
3. Inspect launch media manually for private names, paths, metadata, and unreleased product information.
4. Update release notes for the version being published.
5. Create a Git tag and GitHub Release only after explicit maintainer approval.
6. Publish approved directory, social, and community posts without asking for votes or using voting groups.
7. Reply to feedback with concrete technical answers and record actionable issues.

## Maintainer Review Gate

- [ ] Product name, tagline, copy, screenshots, and video approved
- [ ] Public links resolve without authentication
- [ ] Current release notes match the source version
- [ ] Verification and privacy commands pass
- [ ] No local project names, paths, databases, context packs, or secrets are tracked
- [ ] Tag and GitHub Release decision explicitly approved

## Official References

- Product Hunt launch preparation: https://www.producthunt.com/launch/preparing-for-launch
- Product Hunt launch-day guidance: https://www.producthunt.com/launch/launch-day
- GitHub social preview guidance: https://docs.github.com/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview
