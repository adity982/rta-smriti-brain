import hmac
import ipaddress
import json
import mimetypes
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .context import build_context_pack, build_continuation_prompt
from .db import (
    attach_memory_provenance, connect, get_project_settings, graph, ingest_repo, init_schema,
    latest_checkpoint, reflect, remember, save_checkpoint, search, stale_check, update_project_settings,
)
from .parsers import ParserRegistry
from .project import bootstrap_project, mcp_config_payload, runtime_shell, shell_cli_command, projects_list, self_check
from .repository import canonical_root, canonical_root_key, repository_state, trusted_git_candidates
from .watch_daemon import start_watcher, stop_watcher, watcher_status


@dataclass(frozen=True)
class ConsoleConfig:
    tool_root: Path
    brain_dir: Path
    default_db: Path | None = None
    default_project: str | None = None
    capability_token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)


MAX_REQUEST_BYTES = 1_048_576
MAX_TREE_ITEMS = 500
MAX_FILE_PREVIEW_CHARS = 20_000
CAPABILITY_COOKIE = "rta_smriti_cap"


def _trusted_git_candidates() -> list[Path]:
    return trusted_git_candidates()


def resolve_brain_db(config: ConsoleConfig, value: str | Path, must_exist: bool = True) -> Path:
    candidate = Path(value).expanduser().resolve()
    if candidate.suffix.lower() != ".sqlite":
        raise ValueError("brain database must be a .sqlite file")
    brain_root = config.brain_dir.expanduser().resolve()
    try:
        candidate.relative_to(brain_root)
        allowed = True
    except ValueError:
        allowed = False
    if config.default_db and candidate == config.default_db.expanduser().resolve():
        allowed = True
    if not allowed:
        raise ValueError("brain database is outside the configured brain directory")
    if must_exist and not candidate.is_file():
        raise ValueError(f"brain database does not exist: {candidate}")
    if candidate.exists() and candidate.stat().st_nlink > 1:
        raise ValueError("hard-linked brain databases are not allowed")
    return candidate


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
            if db_path.is_symlink() or db_path.stat().st_nlink > 1:
                continue
            conn = _open_db(db_path)
            init_schema(conn)
            payload = projects_list(conn)
            for project in payload["projects"]:
                health = self_check(conn, project=project["name"], check_files=False)
                project_id = int(project["id"])
                git = repository_state(project.get("root_path"))
                entries.append(
                    {
                        "status": "ok",
                        "db_path": str(db_path),
                        "db_file": db_path.name,
                        "project": project["name"],
                        "root_path": project.get("root_path"),
                        "repository_identity": project.get("repository_identity"),
                        "canonical_root": canonical_root(project["root_path"]) if project.get("root_path") else None,
                        "git": git,
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
    roots_by_project: dict[str, dict[str, str]] = {}
    for entry in entries:
        if entry.get("status") != "ok" or not entry.get("canonical_root"):
            continue
        root = str(entry["canonical_root"])
        roots_by_project.setdefault(str(entry["project"]).casefold(), {})[canonical_root_key(root)] = root
    for entry in entries:
        roots = roots_by_project.get(str(entry.get("project", "")).casefold(), {})
        entry["root_conflict"] = len(roots) > 1
        if len(roots) > 1:
            entry["root_conflict_roots"] = sorted(roots.values())
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
        clauses = ["m.project_id = ?"]
        params: list = [int(row["id"])]
        if query:
            clauses.append("LOWER(m.text) LIKE ?")
            params.append(f"%{query.lower()}%")
        if memory_type:
            clauses.append("m.type = ?")
            params.append(memory_type)
        if pramana:
            clauses.append("m.pramana = ?")
            params.append(pramana)
        if status:
            clauses.append("m.status = ?")
            params.append(status)
        params.append(max(1, min(int(limit), 500)))
        rows = []
        for item in conn.execute(
                f"""
                SELECT m.id, m.type, m.pramana, m.text, m.confidence, m.priority, m.status,
                       m.created_at, m.updated_at,
                       mp.source_path AS provenance_source_path,
                       mp.source_hash AS provenance_source_hash,
                       mp.command AS provenance_command,
                       mp.timestamp AS provenance_timestamp,
                       mp.verification_status AS provenance_verification_status,
                       mp.metadata_json AS provenance_metadata_json
                FROM memories m
                LEFT JOIN memory_provenance mp ON mp.memory_id = m.id
                WHERE {" AND ".join(clauses)}
                ORDER BY m.status = 'pinned' DESC, m.priority DESC, m.updated_at DESC, m.id DESC
                LIMIT ?
                """,
                params,
            ):
            memory = dict(item)
            attach_memory_provenance(memory)
            rows.append(memory)
        return {"status": "ok", "project": project, "memories": rows}
    finally:
        conn.close()


def _relative_source_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("file tree requires a relative path that cannot traverse outside the project")
    return "/".join(parts)


def read_file_tree(
    db_path: str | Path,
    project: str,
    prefix: str = "",
    query: str = "",
    limit: int = MAX_TREE_ITEMS,
) -> dict:
    conn = _open_db(db_path)
    try:
        init_schema(conn)
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
        if not row:
            return {"status": "ok", "project": project, "prefix": "", "entries": [], "total_files": 0, "truncated": False}
        project_id = int(row["id"])
        safe_prefix = _relative_source_path(prefix)
        normalized_query = str(query or "").strip().lower()
        item_limit = max(1, min(int(limit), MAX_TREE_ITEMS))
        total_files = int(conn.execute(
            "SELECT COUNT(*) AS count FROM sources WHERE project_id = ? AND kind = 'file'",
            (project_id,),
        ).fetchone()["count"])
        if normalized_query:
            escaped_query = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            matched_files = int(conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM sources
                WHERE project_id = ? AND kind = 'file' AND LOWER(title) LIKE ? ESCAPE '\\'
                """,
                (project_id, f"%{escaped_query}%"),
            ).fetchone()["count"])
            rows = conn.execute(
                """
                SELECT title, metadata_json, updated_at
                FROM sources
                WHERE project_id = ? AND kind = 'file' AND LOWER(title) LIKE ? ESCAPE '\\'
                ORDER BY LOWER(title), title
                LIMIT ?
                """,
                (project_id, f"%{escaped_query}%", item_limit + 1),
            ).fetchall()
            matches = []
            for source in rows[:item_limit]:
                relative_path = _relative_source_path(source["title"])
                try:
                    metadata = json.loads(source["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                matches.append(
                    {
                        "kind": "file",
                        "name": relative_path.rsplit("/", 1)[-1],
                        "relative_path": relative_path,
                        "size": int(metadata.get("size") or 0),
                        "updated_at": source["updated_at"],
                    }
                )
            return {
                "status": "ok",
                "project": project,
                "prefix": safe_prefix,
                "query": normalized_query,
                "entries": matches,
                "total_files": total_files,
                "matched_files": matched_files,
                "truncated": matched_files > item_limit,
            }

        prefix_marker = f"{safe_prefix}/" if safe_prefix else ""
        escaped_prefix = prefix_marker.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_pattern = f"{escaped_prefix}%"
        remainder_start = len(prefix_marker) + 1
        descendants = int(conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM sources
            WHERE project_id = ? AND kind = 'file' AND title LIKE ? ESCAPE '\\'
            """,
            (project_id, like_pattern),
        ).fetchone()["count"])
        directory_rows = conn.execute(
            """
            SELECT substr(remainder, 1, instr(remainder, '/') - 1) AS name, COUNT(*) AS count
            FROM (
                SELECT substr(title, ?) AS remainder
                FROM sources
                WHERE project_id = ? AND kind = 'file' AND title LIKE ? ESCAPE '\\'
            )
            WHERE instr(remainder, '/') > 0
            GROUP BY name
            ORDER BY LOWER(name), name
            LIMIT ?
            """,
            (remainder_start, project_id, like_pattern, item_limit + 1),
        ).fetchall()
        directories = [
            {
                "kind": "directory",
                "name": str(source["name"]),
                "relative_path": f"{prefix_marker}{source['name']}" if prefix_marker else str(source["name"]),
                "count": int(source["count"]),
            }
            for source in directory_rows
        ]
        remaining_limit = max(0, item_limit + 1 - len(directories))
        file_rows = conn.execute(
            """
            SELECT title, metadata_json, updated_at
            FROM sources
            WHERE project_id = ? AND kind = 'file' AND title LIKE ? ESCAPE '\\'
              AND instr(substr(title, ?), '/') = 0
            ORDER BY LOWER(title), title
            LIMIT ?
            """,
            (project_id, like_pattern, remainder_start, remaining_limit),
        ).fetchall()
        files = []
        for source in file_rows:
            relative_path = _relative_source_path(source["title"])
            remainder = relative_path[len(prefix_marker):]
            try:
                metadata = json.loads(source["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            files.append(
                {
                    "kind": "file",
                    "name": remainder,
                    "relative_path": relative_path,
                    "size": int(metadata.get("size") or 0),
                    "updated_at": source["updated_at"],
                }
            )
        entries = [*directories, *files]
        return {
            "status": "ok",
            "project": project,
            "prefix": safe_prefix,
            "entries": entries[:item_limit],
            "total_files": total_files,
            "descendant_files": descendants,
            "truncated": len(entries) > item_limit,
        }
    finally:
        conn.close()


def read_file_preview(db_path: str | Path, project: str, relative_path: str) -> dict:
    conn = _open_db(db_path)
    try:
        init_schema(conn)
        safe_path = _relative_source_path(relative_path)
        row = conn.execute(
            """
            SELECT s.id, s.title, s.hash, s.metadata_json, s.updated_at
            FROM sources s
            JOIN projects p ON p.id = s.project_id
            WHERE p.name = ? AND s.kind = 'file' AND s.title = ?
            """,
            (project, safe_path),
        ).fetchone()
        if not row:
            return {"status": "ok", "project": project, "file": None}
        chunks = conn.execute(
            "SELECT text FROM chunks WHERE source_id = ? ORDER BY ordinal",
            (int(row["id"]),),
        ).fetchall()
        content = "\n\n".join(str(item["text"]) for item in chunks)
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return {
            "status": "ok",
            "project": project,
            "file": {
                "relative_path": safe_path,
                "name": safe_path.rsplit("/", 1)[-1],
                "size": int(metadata.get("size") or 0),
                "sha256": row["hash"],
                "updated_at": row["updated_at"],
                "content": content[:MAX_FILE_PREVIEW_CHARS],
                "preview_truncated": len(content) > MAX_FILE_PREVIEW_CHARS,
            },
        }
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
        "package-lock.json",
        ".github/workflows/ci.yml",
        ".gitignore",
    ]
    checks = [{"name": name, "ok": (tool_root / name).exists()} for name in required_files]
    license_exists = any((tool_root / name).exists() for name in ("LICENSE", "LICENSE.md", "COPYING"))
    checks.append({"name": "LICENSE", "ok": license_exists, "note": "MIT license present." if license_exists else "Choose and add a real license before public release."})

    git_ok = False
    git_clean = False
    git_note = "Not initialized as a git repository."
    try:
        git_executable = next((str(path) for path in trusted_git_candidates()), None)
        if not git_executable:
            raise FileNotFoundError("Git was not found in a trusted installation directory")
        result = subprocess.run(
            [git_executable, "-C", str(tool_root), "rev-parse", "--is-inside-work-tree"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        git_ok = result.returncode == 0 and result.stdout.strip() == "true"
        if git_ok:
            status = subprocess.run([git_executable, "-C", str(tool_root), "status", "--short"], text=True, capture_output=True, timeout=5)
            git_clean = status.returncode == 0 and not status.stdout.strip()
            git_note = "Repository detected."
    except Exception as exc:
        git_note = f"Git check failed: {exc}"

    checks.append({"name": "git repository", "ok": git_ok, "note": git_note})
    checks.append(
        {
            "name": "clean working tree",
            "ok": git_ok and git_clean,
            "note": "All release files are committed." if git_clean else "Commit or intentionally remove outstanding changes before publishing.",
        }
    )
    ready_count = sum(1 for item in checks if item["ok"])
    return {
        "status": "ok",
        "tool_root": str(tool_root),
        "ready": ready_count == len(checks),
        "checks": checks,
        "commands": [
            "npm audit --audit-level=high",
            "npm run build",
            "npm run build:launch",
            "python scripts/privacy_scan.py",
            "python -m unittest discover -s tests -v",
            "python -m compileall -q rta_brain tests scripts",
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
        "shell": runtime_shell(),
        "cli_command": shell_cli_command(config.tool_root),
        "projects": scan_brain_databases(config.brain_dir),
        "publish": publish_readiness(config.tool_root),
    }


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    if length > MAX_REQUEST_BYTES:
        raise ValueError("request body exceeds the 1 MB limit")
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
    expected = f"http://{handler.headers.get('Host') or ''}"
    if origin.startswith("http://") or origin.startswith("https://"):
        parsed = urlparse(origin)
        return f"{parsed.scheme}://{parsed.netloc}" == expected
    return origin.startswith(expected + "/")


def is_local_request(handler: BaseHTTPRequestHandler) -> bool:
    hostname = urlparse(f"//{handler.headers.get('Host') or ''}").hostname
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    client = getattr(handler, "client_address", ("127.0.0.1", 0))[0]
    try:
        return ipaddress.ip_address(client).is_loopback
    except ValueError:
        return client == "localhost"


def _request_capability(handler: BaseHTTPRequestHandler) -> str:
    supplied = handler.headers.get("X-Rta-Smriti-Token") or ""
    if supplied:
        return supplied
    raw_cookie = handler.headers.get("Cookie") or ""
    if not raw_cookie:
        return ""
    try:
        cookies = SimpleCookie()
        cookies.load(raw_cookie)
        morsel = cookies.get(CAPABILITY_COOKIE)
        return morsel.value if morsel else ""
    except Exception:
        return ""


def is_authorized_header_request(handler: BaseHTTPRequestHandler, config: ConsoleConfig) -> bool:
    supplied = handler.headers.get("X-Rta-Smriti-Token") or ""
    return bool(supplied) and hmac.compare_digest(supplied, config.capability_token)


def is_authorized_request(handler: BaseHTTPRequestHandler, config: ConsoleConfig) -> bool:
    supplied = _request_capability(handler)
    return bool(supplied) and hmac.compare_digest(supplied, config.capability_token)


def make_handler(config: ConsoleConfig):
    static_dir = Path(__file__).resolve().parent / "static"

    class ConsoleHandler(BaseHTTPRequestHandler):
        server_version = "RtaSmritiConsole/0.1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format, *args):  # noqa: A003
            sys.stderr.write("[rta-console] " + (format % args) + "\n")

        def _security_headers(self) -> None:
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            if status < 400 and is_local_request(self) and is_local_origin(self) and is_authorized_header_request(self, config):
                self.send_header("Set-Cookie", f"{CAPABILITY_COOKIE}={config.capability_token}; HttpOnly; SameSite=Strict; Path=/")
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
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if "assets" in resolved.parts else "no-store")
            self._security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if not is_local_request(self):
                    self._json({"status": "error", "error": {"type": "Forbidden", "message": "non-loopback request rejected"}}, status=403)
                    return
                if parsed.path.startswith("/api/") and (not is_authorized_request(self, config) or not is_local_origin(self)):
                    self._json({"status": "error", "error": {"type": "Forbidden", "message": "valid local capability required"}}, status=403)
                    return
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
                            resolve_brain_db(config, q["db_path"]),
                            q["project"],
                            query=q.get("query", ""),
                            memory_type=q.get("type", ""),
                            pramana=q.get("pramana", ""),
                            status=q.get("status", ""),
                            limit=int(q.get("limit", "100")),
                        )
                    )
                    return
                if parsed.path == "/api/files":
                    q = _query(self)
                    self._json(
                        read_file_tree(
                            resolve_brain_db(config, q["db_path"]),
                            q["project"],
                            prefix=q.get("prefix", ""),
                            query=q.get("query", ""),
                            limit=int(q.get("limit", str(MAX_TREE_ITEMS))),
                        )
                    )
                    return
                if parsed.path == "/api/file-preview":
                    q = _query(self)
                    self._json(
                        read_file_preview(
                            resolve_brain_db(config, q["db_path"]),
                            q["project"],
                            q["path"],
                        )
                    )
                    return
                if parsed.path == "/api/graph":
                    q = _query(self)
                    conn = _open_db(resolve_brain_db(config, q["db_path"]))
                    try:
                        self._json(graph(conn, project=q["project"], limit=int(q.get("limit", "120"))))
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/stale-check":
                    q = _query(self)
                    conn = _open_db(resolve_brain_db(config, q["db_path"]))
                    try:
                        self._json(stale_check(conn, project=q["project"]))
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/settings":
                    q = _query(self)
                    conn = _open_db(resolve_brain_db(config, q["db_path"]))
                    try:
                        settings = get_project_settings(conn, q["project"])
                        self._json({
                            "status": "ok", "settings": settings,
                            "parser_capabilities": ParserRegistry(lsp_command=settings["lsp_command"]).capabilities(),
                        })
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/watcher":
                    q = _query(self)
                    db_path = resolve_brain_db(config, q["db_path"])
                    self._json(watcher_status(db_path, q["project"]))
                    return
                if parsed.path == "/api/checkpoint":
                    q = _query(self)
                    conn = _open_db(resolve_brain_db(config, q["db_path"]))
                    try:
                        self._json({"status": "ok", "project": q["project"], "checkpoint": latest_checkpoint(conn, q["project"])})
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/continuation-prompt":
                    q = _query(self)
                    conn = _open_db(resolve_brain_db(config, q["db_path"]))
                    try:
                        self._json({"status": "ok", "project": q["project"], "prompt": build_continuation_prompt(conn, q["project"])})
                    finally:
                        conn.close()
                    return
                if parsed.path == "/api/mcp-config":
                    q = _query(self)
                    db_path = resolve_brain_db(config, q["db_path"])
                    self._json(mcp_config_payload(str(db_path), q["project"], q.get("name", "rta-smriti"), config.tool_root))
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
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._json({"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}, status=400)
            except Exception as exc:
                self._json({"status": "error", "error": {"type": exc.__class__.__name__, "message": "request could not be completed"}}, status=500)

        def do_POST(self) -> None:
            try:
                if not is_local_request(self) or not is_local_origin(self) or not is_authorized_request(self, config):
                    self._json({"status": "error", "error": {"type": "Forbidden", "message": "valid local capability required"}}, status=403)
                    return
                if (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json":
                    self._json({"status": "error", "error": {"type": "UnsupportedMediaType", "message": "application/json is required"}}, status=415)
                    return
                payload = _read_body(self)
                if self.path == "/api/context-pack":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
                    try:
                        self._json(
                            {
                                "status": "ok",
                                "pack": build_context_pack(
                                    conn,
                                    payload["task"],
                                    project=payload["project"],
                                    limit=int(payload.get("limit", 8)),
                                    max_tokens=int(payload.get("max_tokens", 4_000)),
                                ),
                            }
                        )
                    finally:
                        conn.close()
                    return
                if self.path == "/api/search":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
                    try:
                        self._json(search(conn, payload["query"], project=payload.get("project"), limit=int(payload.get("limit", 8))))
                    finally:
                        conn.close()
                    return
                if self.path == "/api/memory":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
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
                                provenance=payload.get("provenance"),
                            )
                        )
                    finally:
                        conn.close()
                    return
                if self.path == "/api/checkpoint":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
                    try:
                        self._json(
                            save_checkpoint(
                                conn,
                                project=payload["project"],
                                objective=payload["objective"],
                                verified_evidence=payload.get("verified_evidence", ""),
                                remaining_gaps=payload.get("remaining_gaps", ""),
                                next_action=payload.get("next_action", ""),
                                prohibited_repetition=payload.get("prohibited_repetition", ""),
                                expected_version=payload.get("expected_version"),
                            )
                        )
                    finally:
                        conn.close()
                    return
                if self.path == "/api/reflect":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
                    try:
                        self._json(reflect(conn, project=payload["project"]))
                    finally:
                        conn.close()
                    return
                if self.path == "/api/ingest-repo":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
                    try:
                        row = conn.execute("SELECT root_path FROM projects WHERE name = ?", (payload["project"],)).fetchone()
                        if not row or not row["root_path"]:
                            raise ValueError("project has no repository path to refresh")
                        self._json(ingest_repo(conn, Path(row["root_path"]), project=payload["project"], force=bool(payload.get("force", False))))
                    finally:
                        conn.close()
                    return
                if self.path == "/api/settings":
                    conn = _open_db(resolve_brain_db(config, payload["db_path"]))
                    try:
                        settings = update_project_settings(conn, payload["project"], payload.get("settings", {}))
                        self._json({
                            "status": "ok", "settings": settings,
                            "parser_capabilities": ParserRegistry(lsp_command=settings["lsp_command"]).capabilities(),
                        })
                    finally:
                        conn.close()
                    return
                if self.path == "/api/watcher":
                    db_path = resolve_brain_db(config, payload["db_path"])
                    project = str(payload["project"])
                    action = str(payload.get("action", "status"))
                    if action == "stop":
                        self._json(stop_watcher(db_path, project))
                        return
                    if action != "start":
                        raise ValueError("watcher action must be start or stop")
                    conn = _open_db(db_path)
                    try:
                        row = conn.execute(
                            "SELECT root_path FROM projects WHERE name = ?", (project,)
                        ).fetchone()
                    finally:
                        conn.close()
                    if not row or not row["root_path"]:
                        raise ValueError("project has no repository path to watch")
                    self._json(
                        start_watcher(
                            db_path,
                            Path(row["root_path"]),
                            project,
                            interval_seconds=float(payload.get("interval", 2.0)),
                        )
                    )
                    return
                if self.path == "/api/bootstrap":
                    config.brain_dir.mkdir(parents=True, exist_ok=True)
                    conn = _open_db(resolve_brain_db(config, config.brain_dir / "_dashboard.sqlite", must_exist=False))
                    try:
                        self._json(
                            bootstrap_project(
                                conn,
                                Path(payload["path"]),
                                payload["project"],
                                config.brain_dir,
                                bool(payload.get("write_agents", False)),
                                config.tool_root,
                                embedding_provider=payload.get("embedding_provider", "hash"),
                            )
                        )
                    finally:
                        conn.close()
                    return
                self._json({"status": "error", "error": {"type": "NotFound", "message": self.path}}, status=404)
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._json({"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}, status=400)
            except Exception as exc:
                self._json({"status": "error", "error": {"type": exc.__class__.__name__, "message": "request could not be completed"}}, status=500)

        def do_OPTIONS(self) -> None:
            self._json({"status": "error", "error": {"type": "MethodNotAllowed", "message": "cross-origin preflight is not supported"}}, status=405)

    return ConsoleHandler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, max_workers: int = 16, **kwargs):
        self._worker_slots = threading.BoundedSemaphore(max_workers)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address) -> None:
        if not self._worker_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


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
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("dashboard host must be loopback-only")
    selected_port = _find_port(host, int(port))
    config = ConsoleConfig(
        tool_root=tool_root.resolve(),
        brain_dir=brain_dir.expanduser().resolve(),
        default_db=default_db.expanduser().resolve() if default_db else None,
        default_project=default_project,
    )
    server = BoundedThreadingHTTPServer((host, selected_port), make_handler(config))
    selected_port = int(server.server_address[1])
    base_url = f"http://{host}:{selected_port}/"
    url = f"{base_url}#token={config.capability_token}"
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
