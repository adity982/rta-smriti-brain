import json
import os
import shlex
import sqlite3
import sys
import tempfile
from pathlib import Path

from .db import connect, doctor, ensure_project, ingest_repo, init_project, stale_check, update_project_settings


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "default"


def project_db_path(brain_dir: Path, project: str) -> Path:
    return brain_dir.resolve() / f"{_slug(project)}.sqlite"


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _cmd_quote(value: str | Path) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def runtime_shell() -> str:
    return "powershell" if os.name == "nt" else "posix"


def _launch_parts(tool_root: Path, script_name: str, module_name: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable)), *(["mcp-server"] if module_name == "rta_brain.mcp_server" else [])]
    script = tool_root / script_name
    if script.is_file():
        return [str(Path(sys.executable)), str(script)]
    return [str(Path(sys.executable)), "-m", module_name]


def _shell_command(parts: list[str], shell: str | None = None) -> str:
    selected = shell or runtime_shell()
    if selected == "powershell":
        return "& " + " ".join(_ps_quote(part) for part in parts)
    return shlex.join(parts)


def shell_quote(value: str | Path, shell: str | None = None) -> str:
    return _ps_quote(value) if (shell or runtime_shell()) == "powershell" else shlex.quote(str(value))


def shell_cli_command(tool_root: Path, shell: str | None = None) -> str:
    return _shell_command(_launch_parts(tool_root, "rta-brain.py", "rta_brain.cli"), shell)


def shell_mcp_command(tool_root: Path, shell: str | None = None) -> str:
    return _shell_command(_launch_parts(tool_root, "rta-brain-mcp.py", "rta_brain.mcp_server"), shell)


def _mcp_launch(tool_root: Path) -> tuple[str, list[str]]:
    parts = _launch_parts(tool_root, "rta-brain-mcp.py", "rta_brain.mcp_server")
    return parts[0], parts[1:]


def _safe_agent_target(repo_path: Path, name: str) -> Path:
    root = repo_path.resolve()
    target = root / name
    try:
        target.parent.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"agent target escapes the project root: {target}") from exc
    if target.exists() or target.is_symlink():
        stat = target.lstat()
        reparse = bool(getattr(stat, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if target.is_symlink() or reparse:
            raise ValueError(f"refusing to write agent instructions through a link: {target}")
        if stat.st_nlink > 1:
            raise ValueError(f"refusing to replace hard-linked agent instructions: {target}")
    return target


def _atomic_write_text(target: Path, text: str) -> None:
    _safe_agent_target(target.parent, target.name)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def agent_file_text(tool_root: Path, db_path: Path, project: str, shell: str | None = None) -> str:
    shell = shell or runtime_shell()
    fence = "powershell" if shell == "powershell" else "bash"
    cli = shell_cli_command(tool_root, shell)
    mcp = shell_mcp_command(tool_root, shell)
    return f"""# Rta-Smriti Project Brain

Before repo work, retrieve local context:

```{fence}
{cli} --db {shell_quote(db_path)} context-pack "<task>" --project {shell_quote(project)}
```

Check whether the database is healthy *and* the task can be continued safely:

```{fence}
{cli} --db {shell_quote(db_path)} operational-readiness --project {shell_quote(project)}
```

After meaningful code or docs changes, refresh the repo graph:

```{fence}
{cli} --db {shell_quote(db_path)} ingest-repo . --project {shell_quote(project)}
```

For MCP hosts, configure:

```{fence}
{mcp} --db {shell_quote(db_path)} --project {shell_quote(project)}
```

Rules:

- Confirm the canonical root and Git state before repo work.
- Treat Rta-Smriti output as memory-derived unless freshness is verified.
- Re-read changed files before acting on stale context.
- Do not store secrets or credentials.
- Store one durable fact at a time with `remember`.
- Append approvals, tool outcomes, and consequential decisions with `session-event`.
- Register assets, jobs, QA, retries, fallbacks, and blockers with `work-item`, then run `reconcile`.
- Save a structured `checkpoint` before ending a meaningful work session.
"""


def agent_index_block(tool_root: Path, db_path: Path, project: str, shell: str | None = None) -> str:
    shell = shell or runtime_shell()
    fence = "powershell" if shell == "powershell" else "bash"
    cli = shell_cli_command(tool_root, shell)
    return f"""<!-- BEGIN:rta-smriti-brain -->
## Rta-Smriti Local Brain

Before repo work, retrieve local project context and use it as working memory:

```{fence}
{cli} --db {shell_quote(db_path)} context-pack "<task>" --project {shell_quote(project)}
```

Check continuation readiness before broad exploration:

```{fence}
{cli} --db {shell_quote(db_path)} operational-readiness --project {shell_quote(project)}
```

After meaningful code or docs changes, refresh the repo graph:

```{fence}
{cli} --db {shell_quote(db_path)} ingest-repo . --project {shell_quote(project)}
```

Use the dashboard for inspection:

```{fence}
{cli} --db {shell_quote(db_path)} dashboard --project {shell_quote(project)}
```

Confirm the canonical root before working. Treat brain output as memory-derived until freshness is verified.
Record consequential events and structured work items as they occur. Reconcile state and save a structured checkpoint before ending a meaningful work session.
<!-- END:rta-smriti-brain -->
"""


def upsert_agent_index(repo_path: Path, tool_root: Path, db_path: Path, project: str) -> Path:
    agent_index = _safe_agent_target(repo_path, "AGENTS.md")
    block = agent_index_block(tool_root, db_path, project)
    if not agent_index.exists():
        _atomic_write_text(agent_index, f"# Project Agent Instructions\n\n{block}")
        return agent_index
    current = agent_index.read_text(encoding="utf-8", errors="ignore")
    start = "<!-- BEGIN:rta-smriti-brain -->"
    end = "<!-- END:rta-smriti-brain -->"
    if start in current and end in current:
        before, rest = current.split(start, 1)
        _, after = rest.split(end, 1)
        updated = before.rstrip() + "\n\n" + block + after.lstrip("\n")
    else:
        updated = current.rstrip() + "\n\n" + block
    _atomic_write_text(agent_index, updated)
    return agent_index


def bootstrap_project(
    _compatibility_conn: sqlite3.Connection | None,
    repo_path: Path,
    project: str,
    brain_dir: Path,
    write_agents: bool,
    tool_root: Path,
    embedding_provider: str | None = None,
) -> dict:
    repo_path = repo_path.resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise ValueError(f"project path does not exist or is not a directory: {repo_path}")
    db_path = project_db_path(brain_dir, project)
    if db_path.is_symlink():
        raise ValueError(f"refusing to use a linked brain database: {db_path}")
    if db_path.exists() and db_path.stat().st_nlink > 1:
        raise ValueError(f"refusing to use a hard-linked brain database: {db_path}")
    agent_path = _safe_agent_target(repo_path, "AGENTS.rta-smriti.md") if write_agents else None
    if write_agents:
        _safe_agent_target(repo_path, "AGENTS.md")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    wrote_agent_file = False
    agent_index_path = None
    project_conn = connect(db_path)
    try:
        init_payload = init_project(project_conn, project, str(repo_path))
        settings_payload = (
            update_project_settings(project_conn, project, {"embedding_provider": embedding_provider})
            if embedding_provider
            else None
        )
        if write_agents:
            _atomic_write_text(agent_path, agent_file_text(tool_root, db_path, project))
            agent_index_path = upsert_agent_index(repo_path, tool_root, db_path, project)
            wrote_agent_file = True
        ingest_payload = ingest_repo(project_conn, repo_path, project=project)
    finally:
        project_conn.close()
    cli = shell_cli_command(tool_root)
    mcp = shell_mcp_command(tool_root)
    return {
        "status": "ok",
        "shell": runtime_shell(),
        "project": project,
        "repo_path": str(repo_path),
        "db_path": str(db_path),
        "init": init_payload,
        "settings": settings_payload,
        "ingest": ingest_payload,
        "agent_file": str(agent_path) if wrote_agent_file else None,
        "agent_index_file": str(agent_index_path) if agent_index_path else None,
        "next_commands": {
            "context_pack": f"{cli} --db {shell_quote(db_path)} context-pack \"<task>\" --project {shell_quote(project)}",
            "mcp_server": f"{mcp} --db {shell_quote(db_path)} --project {shell_quote(project)}",
        },
    }


def projects_list(conn: sqlite3.Connection) -> dict:
    from .db import init_schema

    init_schema(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.id, p.name, p.root_path, p.repository_identity, p.created_at,
                   COUNT(DISTINCT s.id) AS sources,
                   COUNT(DISTINCT m.id) AS memories
            FROM projects p
            LEFT JOIN sources s ON s.project_id = p.id
            LEFT JOIN memories m ON m.project_id = p.id
            GROUP BY p.id
            ORDER BY p.name
            """
        )
    ]
    return {"status": "ok", "projects": rows}


def self_check(conn: sqlite3.Connection, project: str, check_files: bool = False) -> dict:
    from .continuity import operational_readiness

    ensure_project(conn, project)
    health = doctor(conn)
    project_id = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()["id"]
    sources = int(conn.execute("SELECT COUNT(*) AS c FROM sources WHERE project_id = ?", (project_id,)).fetchone()["c"])
    memories = int(conn.execute("SELECT COUNT(*) AS c FROM memories WHERE project_id = ? AND status IN ('active', 'pinned')", (project_id,)).fetchone()["c"])
    entities = int(conn.execute("SELECT COUNT(*) AS c FROM entities WHERE project_id = ?", (project_id,)).fetchone()["c"])
    if check_files:
        fresh = stale_check(conn, project=project, deep=True)
        freshness = {"mode": "file-hash", "state": fresh["state"], "fresh": fresh["fresh"], "changed": fresh["changed"], "missing": fresh["missing"], "added": fresh["added"]}
    else:
        freshness = {"mode": "summary", "fresh": None, "changed": None, "missing": None}
    ready = bool(health["fts_enabled"] and (sources > 0 or memories > 0) and (not check_files or freshness.get("state") == "fresh"))
    operational = operational_readiness(conn, project, include_event_count=False)
    return {
        "status": "ok",
        "project": project,
        "ready": ready,
        "database_ready": ready,
        "continuation_ready": operational["continuation_ready"],
        "operational_state": operational["operational_state"],
        "operational_reasons": operational["reasons"],
        "sources": sources,
        "memories": memories,
        "entities": entities,
        "freshness": freshness,
        "suggested_next_command": f"rta-brain context-pack \"<task>\" --project {project}",
    }


def install_local(target: Path, tool_root: Path, shell: str | None = None) -> dict:
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    shell = shell or runtime_shell()
    suffix = ".cmd" if shell == "powershell" else ""
    wrappers = {
        f"rta-brain{suffix}": _launch_parts(tool_root, "rta-brain.py", "rta_brain.cli"),
        f"rta-brain-mcp{suffix}": _launch_parts(tool_root, "rta-brain-mcp.py", "rta_brain.mcp_server"),
    }
    written = []
    for name, parts in wrappers.items():
        wrapper = target / name
        if shell == "powershell":
            invocation = " ".join(_cmd_quote(part) for part in parts)
            content = f"@echo off\nsetlocal\n{invocation} %*\n"
        else:
            content = f"#!/bin/sh\nexec {shlex.join(parts)} \"$@\"\n"
        wrapper.write_text(content, encoding="utf-8", newline="\n")
        if shell == "posix":
            wrapper.chmod(wrapper.stat().st_mode | 0o111)
        written.append(str(wrapper))
    cli_wrapper = target / f"rta-brain{suffix}"
    return {
        "status": "ok",
        "shell": shell,
        "target": str(target),
        "wrappers": written,
        "path_note": f"Add {target} to PATH if it is not already there.",
        "shell_command": _shell_command([str(cli_wrapper)], shell),
        "powershell_command": f"& {_ps_quote(cli_wrapper)}" if shell == "powershell" else None,
    }


def mcp_config_payload(db_path: str, project: str, name: str, tool_root: Path) -> dict:
    command, prefix_args = _mcp_launch(tool_root)
    return {
        "status": "ok",
        "config": {
            "mcpServers": {
                name: {
                    "command": command,
                    "args": [*prefix_args, "--db", str(Path(db_path)), "--project", project],
                }
            }
        },
    }


def mcp_gateway_config_payload(brain_dir: str, name: str, tool_root: Path) -> dict:
    command, prefix_args = _mcp_launch(tool_root)
    return {
        "status": "ok",
        "config": {
            "mcpServers": {
                name: {
                    "command": command,
                    "args": [*prefix_args, "--brain-dir", str(Path(brain_dir).expanduser().resolve())],
                }
            }
        },
    }


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
