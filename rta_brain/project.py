import json
import sqlite3
from pathlib import Path

from .db import doctor, ensure_project, ingest_repo, init_project, stale_check


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "default"


def project_db_path(brain_dir: Path, project: str) -> Path:
    return brain_dir.resolve() / f"{_slug(project)}.sqlite"


def agent_file_text(tool_root: Path, db_path: Path, project: str) -> str:
    cli = tool_root / "rta-brain.cmd"
    mcp = tool_root / "rta-brain-mcp.cmd"
    return f"""# Rta-Smriti Project Brain

Before repo work, retrieve local context:

```powershell
{cli} context-pack "<task>" --project {project} --db {db_path}
```

After meaningful code or docs changes, refresh the repo graph:

```powershell
{cli} ingest-repo . --project {project} --db {db_path}
```

For MCP hosts, configure:

```powershell
{mcp} --db {db_path} --project {project}
```

Rules:

- Treat Rta-Smriti output as memory-derived unless freshness is verified.
- Re-read changed files before acting on stale context.
- Do not store secrets or credentials.
- Store one durable fact at a time with `remember`.
"""


def agent_index_block(tool_root: Path, db_path: Path, project: str) -> str:
    cli = tool_root / "rta-brain.cmd"
    return f"""<!-- BEGIN:rta-smriti-brain -->
## Rta-Smriti Local Brain

Before repo work, retrieve local project context and use it as working memory:

```powershell
{cli} --db {db_path} context-pack "<task>" --project {project}
```

After meaningful code or docs changes, refresh the repo graph:

```powershell
{cli} --db {db_path} ingest-repo . --project {project}
```

Use the dashboard for inspection:

```powershell
{cli} dashboard --db {db_path} --project {project}
```

Treat brain output as memory-derived until freshness is verified.
<!-- END:rta-smriti-brain -->
"""


def upsert_agent_index(repo_path: Path, tool_root: Path, db_path: Path, project: str) -> Path:
    agent_index = repo_path / "AGENTS.md"
    block = agent_index_block(tool_root, db_path, project)
    if not agent_index.exists():
        agent_index.write_text(f"# Project Agent Instructions\n\n{block}", encoding="utf-8")
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
    agent_index.write_text(updated, encoding="utf-8")
    return agent_index


def bootstrap_project(conn: sqlite3.Connection, repo_path: Path, project: str, brain_dir: Path, write_agents: bool, tool_root: Path) -> dict:
    repo_path = repo_path.resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise ValueError(f"project path does not exist or is not a directory: {repo_path}")
    db_path = project_db_path(brain_dir, project)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    project_conn = sqlite3.connect(str(db_path))
    project_conn.row_factory = sqlite3.Row
    try:
        init_payload = init_project(project_conn, project, str(repo_path))
        ingest_payload = ingest_repo(project_conn, repo_path, project=project)
    finally:
        project_conn.close()
    agent_path = repo_path / "AGENTS.rta-smriti.md"
    wrote_agent_file = False
    agent_index_path = None
    if write_agents:
        agent_path.write_text(agent_file_text(tool_root, db_path, project), encoding="utf-8")
        agent_index_path = upsert_agent_index(repo_path, tool_root, db_path, project)
        wrote_agent_file = True
    return {
        "status": "ok",
        "project": project,
        "repo_path": str(repo_path),
        "db_path": str(db_path),
        "init": init_payload,
        "ingest": ingest_payload,
        "agent_file": str(agent_path) if wrote_agent_file else None,
        "agent_index_file": str(agent_index_path) if agent_index_path else None,
        "next_commands": {
            "context_pack": f"{tool_root / 'rta-brain.cmd'} context-pack \"<task>\" --project {project} --db {db_path}",
            "mcp_server": f"{tool_root / 'rta-brain-mcp.cmd'} --db {db_path} --project {project}",
        },
    }


def projects_list(conn: sqlite3.Connection) -> dict:
    from .db import init_schema

    init_schema(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.id, p.name, p.root_path, p.created_at,
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
    ensure_project(conn, project)
    health = doctor(conn)
    project_id = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()["id"]
    sources = int(conn.execute("SELECT COUNT(*) AS c FROM sources WHERE project_id = ?", (project_id,)).fetchone()["c"])
    memories = int(conn.execute("SELECT COUNT(*) AS c FROM memories WHERE project_id = ? AND status IN ('active', 'pinned')", (project_id,)).fetchone()["c"])
    entities = int(conn.execute("SELECT COUNT(*) AS c FROM entities WHERE project_id = ?", (project_id,)).fetchone()["c"])
    if check_files:
        fresh = stale_check(conn, project=project)
        freshness = {"mode": "file-hash", "fresh": fresh["fresh"], "changed": fresh["changed"], "missing": fresh["missing"]}
    else:
        freshness = {"mode": "summary", "fresh": None, "changed": None, "missing": None}
    ready = bool(health["fts_enabled"] and (sources > 0 or memories > 0) and (not check_files or (freshness["changed"] == 0 and freshness["missing"] == 0)))
    return {
        "status": "ok",
        "project": project,
        "ready": ready,
        "sources": sources,
        "memories": memories,
        "entities": entities,
        "freshness": freshness,
        "suggested_next_command": f"rta-brain context-pack \"<task>\" --project {project}",
    }


def install_local(target: Path, tool_root: Path) -> dict:
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    wrappers = {
        "rta-brain.cmd": tool_root / "rta-brain.py",
        "rta-brain-mcp.cmd": tool_root / "rta-brain-mcp.py",
    }
    written = []
    for name, script in wrappers.items():
        wrapper = target / name
        wrapper.write_text(
            f'@echo off\nsetlocal\npython "{script}" %*\n',
            encoding="utf-8",
        )
        written.append(str(wrapper))
    return {
        "status": "ok",
        "target": str(target),
        "wrappers": written,
        "path_note": f"Add {target} to PATH if it is not already there.",
    }


def mcp_config_payload(db_path: str, project: str, name: str, tool_root: Path) -> dict:
    return {
        "status": "ok",
        "config": {
            "mcpServers": {
                name: {
                    "command": str(tool_root / "rta-brain-mcp.cmd"),
                    "args": ["--db", str(Path(db_path)), "--project", project],
                }
            }
        },
    }


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
