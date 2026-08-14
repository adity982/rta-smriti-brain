# Rta-Smriti Brain Agent Instructions

Use this file as an `AGENTS.md` addition for projects that should use Rta-Smriti.

## Before Project Work

If MCP is available, call `brain_context_pack` first with the user's task and the current project name.

If MCP is not available, use the CLI:

0. Verify the project brain is ready:

```powershell
<path-to-rta-smriti>\rta-brain.cmd self-check --project <project-name> --json --db <project-brain.sqlite>
```

1. Run a health check:

```powershell
<path-to-rta-smriti>\rta-brain.cmd doctor --json --db <project-brain.sqlite>
```

2. Build a context pack for the current task:

```powershell
<path-to-rta-smriti>\rta-brain.cmd context-pack "<user task>" --project <project-name> --db <project-brain.sqlite>
```

3. Treat the pack as guidance, not proof. If the pack says indexed files are stale, re-read the changed files before acting.

## During Work

- Store durable decisions with `--pramana sabda` when they come from the user or trusted docs.
- Store direct tool/test/file observations with `--pramana pratyaksha`.
- Store inferences with `--pramana anumana`.
- Store older memory-derived facts with `--pramana smriti`.
- Store creative hypotheses with `--pramana kalpana`, and do not present them as verified.

## After Work

Record only useful durable knowledge:

```powershell
<path-to-rta-smriti>\rta-brain.cmd remember "<one durable fact>" --type <decision|constraint|procedure|bug|evidence|fact> --pramana <pratyaksha|sabda|anumana|smriti|kalpana> --project <project-name> --priority <1-10> --db <project-brain.sqlite>
```

Re-index after meaningful code or doc changes:

```powershell
<path-to-rta-smriti>\rta-brain.cmd ingest-repo <repo-path> --project <project-name> --db <project-brain.sqlite>
```

Ingest important handoffs or long-session summaries:

```powershell
<path-to-rta-smriti>\rta-brain.cmd ingest-thread <thread-or-handoff-path> --project <project-name> --title "<short title>" --db <project-brain.sqlite>
```

Run reflection after bulk memory writes:

```powershell
<path-to-rta-smriti>\rta-brain.cmd reflect --project <project-name> --json --db <project-brain.sqlite>
```

## Safety

- Do not store secrets, tokens, cookies, or private credentials.
- Do not treat stale memories as current.
- Do not mutate project state just because memory suggests it.
- Keep per-project databases separate unless the user explicitly authorizes shared memory.
