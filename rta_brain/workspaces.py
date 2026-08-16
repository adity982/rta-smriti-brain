"""Multi-repository workspace metadata over independently bound projects."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import init_schema, now_iso, search


def _name(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > 200:
        raise ValueError(f"{label} exceeds 200 characters")
    return text


def create_workspace(conn, name: str, description: str = "") -> dict:
    init_schema(conn)
    workspace_name = _name(name, "workspace name")
    description_text = str(description or "").strip()
    if len(description_text) > 2_000:
        raise ValueError("workspace description exceeds 2,000 characters")
    timestamp = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO workspaces(name, description, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET description = excluded.description, updated_at = excluded.updated_at
            """,
            (workspace_name, description_text, timestamp, timestamp),
        )
    return get_workspace(conn, workspace_name)


def _connection_path(conn) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return str(Path(row["file"]).resolve()) if row and row["file"] else ":memory:"


def _existing_brain_path(value: str | Path) -> Path:
    requested = Path(value).expanduser()
    if requested.is_symlink():
        raise ValueError("workspace member brain must not be a linked file")
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"workspace member brain does not exist: {requested}") from exc
    if not resolved.is_file():
        raise ValueError(f"workspace member brain is not a regular file: {resolved}")
    if resolved.stat().st_nlink > 1:
        raise ValueError("workspace member brain must not be a linked file")
    return resolved


def _connect_existing_brain(value: str | Path, *, read_only: bool = False) -> tuple[sqlite3.Connection, Path]:
    resolved = _existing_brain_path(value)
    mode = "ro" if read_only else "rw"
    conn = sqlite3.connect(f"{resolved.as_uri()}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn, resolved


def add_project_to_workspace(
    conn, *, workspace: str, project: str, role: str = "member", db_path: str | Path | None = None,
) -> dict:
    init_schema(conn)
    workspace_name = _name(workspace, "workspace")
    project_name = _name(project, "project")
    role_name = _name(role, "role")
    workspace_row = conn.execute("SELECT id FROM workspaces WHERE name = ?", (workspace_name,)).fetchone()
    if not workspace_row:
        raise ValueError(f"workspace does not exist: {workspace_name}")
    owner_path = _connection_path(conn)
    if db_path:
        member_conn, resolved_member = _connect_existing_brain(db_path)
        member_db_path = str(resolved_member)
        if member_db_path == owner_path:
            member_conn.close()
            member_conn = conn
    else:
        member_db_path = owner_path
        member_conn = conn
    try:
        init_schema(member_conn)
        project_row = member_conn.execute("SELECT id FROM projects WHERE name = ?", (project_name,)).fetchone()
        if not project_row:
            raise ValueError(f"project does not exist in member brain: {project_name}")
    finally:
        if member_conn is not conn:
            member_conn.close()
    with conn:
        conn.execute(
            """
            INSERT INTO workspace_members(workspace_id, db_path, project_name, role, added_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, db_path, project_name) DO UPDATE SET role = excluded.role
            """,
            (int(workspace_row["id"]), member_db_path, project_name, role_name, now_iso()),
        )
        conn.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now_iso(), int(workspace_row["id"])))
    return get_workspace(conn, workspace_name)


def get_workspace(conn, name: str) -> dict:
    init_schema(conn)
    row = conn.execute("SELECT * FROM workspaces WHERE name = ?", (_name(name, "workspace"),)).fetchone()
    if not row:
        raise ValueError(f"workspace does not exist: {name}")
    projects = [dict(item) for item in conn.execute(
        """
        SELECT project_name AS project, role, db_path, added_at
        FROM workspace_members WHERE workspace_id = ? ORDER BY project_name, db_path
        """,
        (int(row["id"]),),
    )]
    if not projects:
        projects = [dict(item) for item in conn.execute(
            """
            SELECT p.name AS project, wp.role, p.root_path, p.repository_identity, wp.added_at,
                   ? AS db_path
            FROM workspace_projects wp JOIN projects p ON p.id = wp.project_id
            WHERE wp.workspace_id = ? ORDER BY p.name
            """,
            (_connection_path(conn), int(row["id"])),
        )]
    return {"status": "ok", "workspace": dict(row), "projects": projects}


def list_workspaces(conn) -> dict:
    init_schema(conn)
    rows = [dict(row) for row in conn.execute(
        """
        SELECT w.*, COUNT(wp.project_name) AS project_count
        FROM workspaces w LEFT JOIN workspace_members wp ON wp.workspace_id = w.id
        GROUP BY w.id ORDER BY w.name
        """
    )]
    return {"status": "ok", "workspaces": rows}


def search_workspace(conn, *, workspace: str, query: str, limit_per_project: int = 4) -> dict:
    details = get_workspace(conn, workspace)
    bounded_limit = max(1, min(20, int(limit_per_project)))
    results = []
    for item in details["projects"]:
        member_path = str(item.get("db_path") or _connection_path(conn))
        owner_path = _connection_path(conn)
        if member_path == owner_path:
            member_conn = conn
        else:
            member_conn, resolved_member = _connect_existing_brain(member_path, read_only=True)
            member_path = str(resolved_member)
        try:
            result = search(
                member_conn, query, project=item["project"], limit=bounded_limit,
                record_recall=False, _initialize=False,
            )
        finally:
            if member_conn is not conn:
                member_conn.close()
        results.append({
            "project": item["project"], "role": item["role"],
            "retrieval": result["retrieval"], "memories": result["memories"], "chunks": result["chunks"],
        })
    return {"status": "ok", "workspace": workspace, "query": str(query), "results": results}
