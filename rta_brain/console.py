import json
import mimetypes
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .context import build_context_pack
from .db import connect, graph, init_schema, reflect, remember, search, stale_check
from .project import bootstrap_project, mcp_config_payload, projects_list, self_check


@dataclass(frozen=True)
class ConsoleConfig:
    tool_root: Path
    brain_dir: Path
    default_db: Path | None = None
    default_project: str | None = None


def _row_count(conn: sqlite3.Connection, table: str, project_id: int | None = None) -> int:
    if project_id is None:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    else:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE project_id = ?", (project_id,)).fetchone()
    return int(row["c"])


def _open_db(db_path: str | Path) -> sqlite3.Connection:
    return connect(Path(db_path).expanduser().resolve())


def scan_brain_databases(brain_dir: Path) -> list[dict]:
    brain_dir = brain_dir.expanduser().resolve()
    if not brain_dir.exists():
        return []
    entries: list[dict] = []
    for db_path in sorted(brain_dir.glob("*.sqlite")):
        conn = None
        try:
            conn = _open_db(db_path)
            init_schema(conn)
            payload = projects_list(conn)
            for project in payload["projects"]:
                health = self_check(conn, project=project["name"], check_files=False)
                project_id = int(project["id"])
                entries.append(
                    {
                        "status": "ok",
                        "db_path": str(db_path),
                        "db_file": db_path.name,
                        "project": project["name"],
                        "root_path": project.get("root_path"),
                        "created_at": project.get("created_at"),
                        "ready": bool(health["ready"]),
                        "sources": int(health["sources"]),
                        "memories": int(health["memories"]),
                        "entities": int(health["entities"]),
                        "chunks": _row_count(conn, "chunks"),
                        "edges": _row_count(conn, "edges", project_id),
                        "freshness": health["freshness"],
                        "suggested_next_command": health["suggested_next_command"],
                    }
                )
        except Exception as exc:
            entries.append(
                {
                    "status": "error",
                    "db_path": str(db_path),
                    "db_file": db_path.name,
                    "project": db_path.stem,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )
        finally:
            if conn is not None:
                conn.close()
    return entries


def read_memories(
    db_path: str | Path,
    project: str,
    query: str = "",
    memory_type: str = "",
    pramana: str = "",
    status: str = "",
    limit: int = 100,
) -> dict:
    conn = _open_db(db_path)
    try:
        init_schema(conn)
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
        if not row:
            return {"status": "ok", "project": project, "memories": []}
        clauses = ["project_id = ?"]
        params: list = [int(row["id"])]
        if query:
            clauses.append("LOWER(text) LIKE ?")
            params.append(f"%{query.lower()}%")
        if memory_type:
            clauses.append("type = ?")
            params.append(memory_type)
        if pramana:
            clauses.append("pramana = ?")
            params.append(pramana)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(max(1, min(int(limit), 500)))
        rows = [
            dict(item)
            for item in conn.execute(
                f"""
                SELECT id, type, pramana, text, confidence, priority, status, created_at, updated_at
                FROM memories
                WHERE {" AND ".join(clauses)}
                ORDER BY status = 'pinned' DESC, priority DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                params,
            )
        ]
        return {"status": "ok", "project": project, "memories": rows}
    finally:
        conn.close()


def publish_readiness(tool_root: Path) -> dict:
    tool_root = tool_root.resolve()
    required_files = [
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "GITHUB_PUBLISH_CHECKLIST.md",
        "pyproject.toml",
        ".gitignore",
    ]
    checks = [{"name": name, "ok": (tool_root / name).exists()} for name in required_files]
    license_exists = any((tool_root / name).exists() for name in ("LICENSE", "LICENSE.md", "COPYING"))
    checks.append({"name": "LICENSE", "ok": license_exists, "note": "Choose and add a real license before public release."})

    git_ok = False
    git_note = "Not initialized as a git repository."
    try:
        result = subprocess.run(
            ["git", "-C", str(tool_root), "rev-parse", "--is-inside-work-tree"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        git_ok = result.returncode == 0 and result.stdout.strip() == "true"
        if git_ok:
            status = subprocess.run(["git", "-C", str(tool_root), "status", "--short"], text=True, capture_output=True, timeout=5)
            git_note = "Working tree clean." if not status.stdout.strip() else "Working tree has uncommitted changes."
    except Exception as exc:
        git_note = f"Git check failed: {exc}"

    checks.append({"name": "git repository", "ok": git_ok, "note": git_note})
    ready_count = sum(1 for item in checks if item["ok"])
    return {
        "status": "ok",
        "tool_root": str(tool_root),
        "ready": ready_count == len(checks),
        "checks": checks,
        "commands": [
            "python -m unittest discover -s tests -v",
            "python -m compileall -q rta_brain tests",
            "pip install -e . --dry-run --no-deps",
            "git init",
            "git add .",
            "git commit -m \"feat: launch rta-smriti brain\"",
        ],
    }


def dashboard_snapshot(config: ConsoleConfig) -> dict:
    return {
        "status": "ok",
        "brain_dir": str(config.brain_dir.expanduser().resolve()),
        "default_db": str(config.default_db) if config.default_db else None,
        "default_project": config.default_project,
        "projects": scan_brain_databases(config.brain_dir),
        "publish": publish_readiness(config.tool_root),
    }


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _query(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    parsed = urlparse(handler.path)
    values = parse_qs(parsed.query)
    return {key: value[-1] for key, value in values.items() if value}


def resolve_static_asset(static_dir: Path, requested_path: str) -> Path | None:
    static_root = static_dir.resolve()
    asset = "index.html" if requested_path in ("", "/") else requested_path.lstrip("/")
    candidate = (static_root / asset).resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError:
        return None
    return candidate


def is_local_origin(handler: BaseHTTPRequestHandler) -> bool:
    origin = handler.headers.get("Origin") or handler.headers.get("Referer")
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def make_handler(config: ConsoleConfig):
    static_dir = Path(__file__).resolve().parent / "static"

    class ConsoleHandler(BaseHTTPRequestHandler):
        server_version = "RtaSmritiConsole/0.1"

        def log_message(self, format, *args):  # noqa: A003
            sys.stderr.write("[rta-console] " + (format % args) + "\n")

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path) -> None:
            resolved = path.resolve()
            if not resolved.exists() or not resolved.is_file():
                self.send_error(404)
                return
            body = resolved.read_bytes()
            ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/health":
                    self._json(dashboard_snapshot(config))
                    return
                if parsed.path == "/api/projects":
                    self._json({"status": "ok", "projects": scan_brain_databases(config.brain_dir)})
                    return
                if parsed.path == "/api/memories":
                    q = _query(self)
                    self._json(
                        read_memories(
                            q["db_path"],
                            q["project"],
                            query=q.get("query", ""),
                            memory_type=q.get("type", ""),
                            pramana=q.get("pramana", ""),
                            status=q.get("status", ""),
                            limit=int(q.get("limit", "100")),
                        )
                    )
                    return
                if parsed.path == "/api/graph":
                    q = _query(self)
                    conn = _open_db(q["db_path"])
                    try:
                        self._json(graph(conn, project=q["project"], limit=int(q.get("limit", "120"))))
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/stale-check":
                    q = _query(self)
                    conn = _open_db(q["db_path"])
                    try:
                        self._json(stale_check(conn, project=q["project"]))
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/mcp-config":
                    q = _query(self)
                    self._json(mcp_config_payload(q["db_path"], q["project"], q.get("name", "rta-smriti"), config.tool_root))
                    return
                if parsed.path == "/api/publish-readiness":
                    self._json(publish_readiness(config.tool_root))
                    return
                if parsed.path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return
                asset = resolve_static_asset(static_dir, parsed.path)
                if asset is None:
                    self.send_error(404)
                    return
                self._file(asset)
            except Exception as exc:
                self._json({"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}, status=500)

        def do_POST(self) -> None:
            try:
                if not is_local_origin(self):
                    self._json({"status": "error", "error": {"type": "Forbidden", "message": "non-local origin rejected"}}, status=403)
                    return
                payload = _read_body(self)
                if self.path == "/api/context-pack":
                    conn = _open_db(payload["db_path"])
                    try:
                        self._json(
                            {
                                "status": "ok",
                                "pack": build_context_pack(
                                    conn,
                                    payload["task"],
                                    project=payload["project"],
                                    limit=int(payload.get("limit", 8)),
                                ),
                            }
                        )
                    finally:
                        conn.close()
                    return
                if self.path == "/api/search":
                    conn = _open_db(payload["db_path"])
                    try:
                        self._json(search(conn, payload["query"], project=payload.get("project"), limit=int(payload.get("limit", 8))))
                    finally:
                        conn.close()
                    return
                if self.path == "/api/memory":
                    conn = _open_db(payload["db_path"])
                    try:
                        self._json(
                            remember(
                                conn,
                                payload["text"],
                                project=payload["project"],
                                memory_type=payload.get("type", "fact"),
                                pramana=payload.get("pramana", "smriti"),
                                confidence=float(payload.get("confidence", 0.75)),
                                priority=int(payload.get("priority", 5)),
                            )
                        )
                    finally:
                        conn.close()
                    return
                if self.path == "/api/reflect":
                    conn = _open_db(payload["db_path"])
                    try:
                        self._json(reflect(conn, project=payload["project"]))
                    finally:
                        conn.close()
                    return
                if self.path == "/api/bootstrap":
                    db_path = Path(payload.get("db_path") or config.brain_dir / "_dashboard.sqlite")
                    conn = _open_db(db_path)
                    try:
                        self._json(
                            bootstrap_project(
                                conn,
                                Path(payload["path"]),
                                payload["project"],
                                Path(payload.get("brain_dir") or config.brain_dir),
                                bool(payload.get("write_agents", True)),
                                config.tool_root,
                            )
                        )
                    finally:
                        conn.close()
                    return
                self._json({"status": "error", "error": {"type": "NotFound", "message": self.path}}, status=404)
            except Exception as exc:
                self._json({"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}, status=500)

    return ConsoleHandler


def _find_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"no available port found from {preferred} to {preferred + 49}")


def run_dashboard(
    tool_root: Path,
    brain_dir: Path,
    default_db: Path | None = None,
    default_project: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> dict:
    selected_port = _find_port(host, int(port))
    config = ConsoleConfig(
        tool_root=tool_root.resolve(),
        brain_dir=brain_dir.expanduser().resolve(),
        default_db=default_db.expanduser().resolve() if default_db else None,
        default_project=default_project,
    )
    server = ThreadingHTTPServer((host, selected_port), make_handler(config))
    url = f"http://{host}:{selected_port}/"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"Rta-Smriti Operator Console: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"status": "ok", "url": url}
