# Rta-Smriti Brain Launch Kit

This is the source of truth for the GitHub and Product Hunt launch. Replace only the bracketed public URLs after the repository and Product Hunt page exist.

## Positioning

**Product:** Rta-Smriti Brain

**Tagline (53 characters):**

```text
Stop re-explaining your project to every new AI chat.
```

**One-liner:**

```text
Local project memory and context packs for AI coding agents.
```

**Simple explanation:**

AI coding agents are powerful, but every new chat starts with amnesia. Rta-Smriti gives each software project a private local brain. It indexes the repository, remembers durable decisions, preserves long-session handoffs, and prepares a focused context pack for the next task. The memory stays on your machine.

## Product Hunt Fields

**Name**

```text
Rta-Smriti Brain
```

**Tagline**

```text
Stop re-explaining your project to every new AI chat.
```

**Description (under 500 characters)**

```text
Give every software project a private local brain. Rta-Smriti indexes repository structure, remembers durable decisions, preserves long agent-session handoffs, and generates focused context packs for Codex, Claude Code, Cursor, and other agents. SQLite, CLI, MCP, and the visual operator console all run locally with no account, telemetry, or cloud database.
```

**Topics**

```text
Developer Tools, Artificial Intelligence, Open Source, Productivity, GitHub
```

**Links**

```text
Website: https://sulabhdubey.github.io/rta-smriti-brain/
GitHub: https://github.com/sulabhdubey/rta-smriti-brain
Video: [PUBLIC-YOUTUBE-URL]
```

## Maker Comment

```text
AI coding agents are getting stronger, but the project memory around them still disappears when a chat gets long, a session ends, or you switch tools.

I built Rta-Smriti Brain to move that memory out of the chat and into the project. It combines repository structure, durable decisions, long-session handoffs, and task-specific context packs in a local SQLite brain. The operator console lets you inspect the graph, browse indexed files, review memories, check freshness, and prepare context for any agent.

The unusual part is the Pramana evidence model. An observed test result, a trusted human instruction, an inference, a prior memory, and a hypothesis remain different kinds of knowledge instead of becoming one undifferentiated memory blob.

This is an alpha developer release. It is open source, local-first, and already tested across six project brains, including a 26,482-file repository. I would especially value feedback on onboarding, retrieval quality, and integrations with your preferred coding agent.
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
5. YouTube video generated from `launch-video/`

Use `launch-assets/product-hunt/thumbnail-240.png` as the thumbnail.

## Launch Posts

**LinkedIn / X**

```text
I built Rta-Smriti Brain because every new AI coding chat kept forgetting the project.

It gives each repository a private local brain: repo structure, durable decisions, long-session handoffs, evidence labels, and focused context packs for any coding agent.

Open source. SQLite. CLI + MCP + visual operator console. No account or telemetry.

https://github.com/sulabhdubey/rta-smriti-brain
[PRODUCT-HUNT-URL]
```

**Show HN**

```text
Show HN: Rta-Smriti Brain - local project memory for AI coding agents

I built an open-source local memory layer that indexes repository structure, durable decisions, and long agent-session handoffs into SQLite, then generates bounded context packs for a concrete task. It includes a CLI, stdio MCP server, and an inspectable React operator console. The evidence model keeps observed facts, trusted instructions, inferences, memories, and hypotheses distinct. I would value feedback on retrieval quality and agent integrations.
```

## Launch-Day Sequence

1. Create the public GitHub repository and set the social preview to `launch-assets/social/github-social-preview.png`.
2. Confirm the default branch, description, topics, Pages workflow, Discussions, and vulnerability reporting.
3. Create release `v0.3.0-alpha` using `docs/RELEASE_NOTES_v0.3.0-alpha.md`.
4. Upload the MP4 to YouTube as an unlisted or public full URL and add captions if narration is later added.
5. Schedule Product Hunt for 12:01 a.m. Pacific and upload the thumbnail plus four gallery images.
6. Add the maker comment immediately after launch.
7. Publish the GitHub, Product Hunt, LinkedIn/X, and Show HN posts.
8. Reply to feedback with concrete answers; do not ask for upvotes or use voting groups.

## Human Review Gate

- [ ] Product name and tagline approved
- [ ] Public GitHub owner/repository URL inserted
- [ ] YouTube URL inserted
- [ ] Product Hunt maker profile and launch date selected
- [ ] Screenshots and video visually approved
- [ ] Final commit and release tag approved
- [ ] No real local project names, paths, databases, context packs, or secrets in tracked files

## Official References

- Product Hunt launch preparation: https://www.producthunt.com/launch/preparing-for-launch
- Product Hunt launch-day guidance: https://www.producthunt.com/launch/launch-day
- GitHub social preview guidance: https://docs.github.com/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview
