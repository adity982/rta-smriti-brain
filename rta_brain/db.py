import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .embeddings import cosine_similarity, create_provider
from .ingest import (
    _lexical_root_for_candidate,
    build_file_record,
    chunk_text,
    effective_file_limit,
    extract_terms,
    read_text,
    sha256_text,
    walk_repo,
)
from .parsers import ParserRegistry
from .repository import canonical_root, repository_identity, same_root, stable_git_identity


VALID_PRAMANA = {"pratyaksha", "sabda", "anumana", "smriti", "kalpana"}
MAX_THREAD_BYTES = 10 * 1024 * 1024
MAX_THREAD_PROMOTIONS = 100
MAX_SEARCH_LIMIT = 50
MAX_GRAPH_LIMIT = 500
DEFAULT_PROJECT_SETTINGS = {
    "max_file_bytes": 512_000,
    "parser_adapter": "auto",
    "lsp_command": "",
    "embedding_provider": "none",
    "embedding_model": "all-MiniLM-L6-v2",
    "hybrid_weight": 0.45,
}


def _repository_identities_match(
    stored_identity: str | None,
    requested_identity: str | None,
    requested_root: str | Path,
) -> bool:
    if stored_identity == requested_identity:
        return True
    if not stored_identity or not requested_identity:
        return False
    if stored_identity.startswith("git:") and requested_identity.startswith("git-local:"):
        return stable_git_identity(requested_root) == stored_identity
    return False
QUERY_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "what", "when", "where", "which", "with",
    "code", "explain", "file", "files", "focused", "next", "prepare",
    "safest", "step", "task",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & 0x400)


def _prepare_database_path(db_path: Path) -> Path:
    requested = Path(db_path).expanduser()
    if requested.is_symlink():
        raise ValueError(f"brain database must not be a linked file: {requested}")
    resolved = requested.resolve()
    parent = resolved.parent
    parent_existed = parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or _is_reparse_point(parent) or not parent.is_dir():
        raise ValueError(f"brain database directory is not a safe directory: {parent}")
    if os.name != "nt" and not parent_existed:
        parent.chmod(0o700)

    if not resolved.exists():
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(resolved, flags, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
    try:
        stat = resolved.lstat()
    except OSError as exc:
        raise ValueError(f"brain database is not accessible: {resolved}") from exc
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or _is_reparse_point(resolved)
        or stat.st_nlink != 1
    ):
        raise ValueError(f"brain database must be an existing unlinked regular file: {resolved}")
    if os.name != "nt":
        resolved.chmod(0o600)
    return resolved


def connect(db_path: Path) -> sqlite3.Connection:
    database = _prepare_database_path(db_path)
    conn = sqlite3.connect(str(database))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        for attempt in range(50):
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 49:
                    raise
                time.sleep(0.02)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA trusted_schema = OFF")
    except Exception:
        conn.close()
        raise
    if os.name != "nt":
        if database.stat().st_uid != os.getuid():
            conn.close()
            raise PermissionError(f"brain database is owned by another user: {database}")
        for sidecar in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
            if sidecar.exists() and sidecar.is_file() and not sidecar.is_symlink() and sidecar.stat().st_uid == os.getuid():
                os.chmod(sidecar, 0o600)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT,
            repository_identity TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            path TEXT,
            title TEXT,
            hash TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, kind, path)
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            hash TEXT NOT NULL,
            UNIQUE(source_id, ordinal)
        );

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            pramana TEXT NOT NULL,
            text TEXT NOT NULL,
            confidence REAL NOT NULL,
            priority INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_provenance (
            memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            source_path TEXT,
            source_hash TEXT,
            command TEXT,
            timestamp TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            objective TEXT NOT NULL,
            verified_evidence TEXT NOT NULL DEFAULT '',
            remaining_gaps TEXT NOT NULL DEFAULT '',
            next_action TEXT NOT NULL DEFAULT '',
            prohibited_repetition TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'operator',
            trigger TEXT NOT NULL DEFAULT 'manual',
            session_id TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS governance_policies (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('constraint', 'failed_approach', 'fragile_path', 'required_check', 'prohibited_repetition')),
            statement TEXT NOT NULL,
            effect TEXT NOT NULL CHECK(effect IN ('warn', 'block')),
            action_contains TEXT NOT NULL DEFAULT '',
            path_glob TEXT NOT NULL DEFAULT '',
            required_check TEXT NOT NULL DEFAULT '',
            pramana TEXT NOT NULL,
            confidence REAL NOT NULL,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            overrideable INTEGER NOT NULL DEFAULT 1 CHECK(overrideable IN (0, 1)),
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'retired')),
            retired_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            retired_at TEXT
        );

        CREATE TABLE IF NOT EXISTS governance_receipts (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            path TEXT,
            actor TEXT NOT NULL,
            initial_decision TEXT NOT NULL,
            final_decision TEXT NOT NULL,
            override_reason TEXT NOT NULL,
            matched_policy_ids_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS governance_decisions (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            action_digest TEXT NOT NULL,
            policy_digest TEXT NOT NULL,
            decision TEXT NOT NULL,
            valid_until TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workspace_projects (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'member',
            added_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, project_id)
        );

        CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            db_path TEXT NOT NULL,
            project_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            added_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, db_path, project_name)
        );

        CREATE TABLE IF NOT EXISTS memory_feedback (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
            outcome TEXT NOT NULL CHECK(outcome IN ('helpful', 'neutral', 'harmful')),
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, type, canonical_key)
        );

        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            from_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            to_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
            memory_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, from_entity_id, relation, to_entity_id, source_id, memory_id)
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY,
            memory_id INTEGER REFERENCES memories(id) ON DELETE CASCADE,
            source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
            chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
            locator TEXT,
            quote_hash TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recall_logs (
            id INTEGER PRIMARY KEY,
            project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
            query TEXT NOT NULL,
            selected_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS repo_manifests (
            project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            digest TEXT NOT NULL,
            file_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_settings (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, key)
        );

        CREATE TABLE IF NOT EXISTS file_hash_cache (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, path)
        );

        CREATE TABLE IF NOT EXISTS chunk_embeddings (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, chunk_id, provider, model)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            memory_id UNINDEXED,
            project_id UNINDEXED,
            text,
            type,
            pramana
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
            chunk_id UNINDEXED,
            source_id UNINDEXED,
            project_id UNINDEXED,
            path UNINDEXED,
            text
        );

        CREATE INDEX IF NOT EXISTS idx_edges_from_entity ON edges(from_entity_id);
        CREATE INDEX IF NOT EXISTS idx_edges_to_entity ON edges(to_entity_id);
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_project ON edges(project_id);
        CREATE INDEX IF NOT EXISTS idx_edges_project_source_id ON edges(project_id, source_id, id);
        CREATE INDEX IF NOT EXISTS idx_edges_project_memory_id ON edges(project_id, memory_id, id);
        CREATE INDEX IF NOT EXISTS idx_sources_project_kind_title ON sources(project_id, kind, title);
        CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_project_provider ON chunk_embeddings(project_id, provider, model);
        CREATE INDEX IF NOT EXISTS idx_checkpoints_project_updated ON checkpoints(project_id, updated_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_governance_policies_project_status ON governance_policies(project_id, status, id);
        CREATE INDEX IF NOT EXISTS idx_governance_receipts_project_created ON governance_receipts(project_id, created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_governance_decisions_project_created ON governance_decisions(project_id, created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_feedback_memory_created ON memory_feedback(memory_id, created_at DESC);
        """
    )
    try:
        # Serialize introspection and ALTER statements across dashboard, MCP, and
        # daemon connections opening an older brain at the same time.
        conn.execute("BEGIN IMMEDIATE")
        project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
        if "repository_identity" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN repository_identity TEXT")
        checkpoint_columns = {row["name"] for row in conn.execute("PRAGMA table_info(checkpoints)")}
        if "version" not in checkpoint_columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
        if "source" not in checkpoint_columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN source TEXT NOT NULL DEFAULT 'operator'")
        if "trigger" not in checkpoint_columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN trigger TEXT NOT NULL DEFAULT 'manual'")
        if "session_id" not in checkpoint_columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN session_id TEXT")
        conn.execute(
            """
            INSERT OR IGNORE INTO memory_provenance(memory_id, timestamp, verification_status, metadata_json)
            SELECT id, created_at, 'unverified', '{}' FROM memories
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def ensure_project(
    conn: sqlite3.Connection,
    name: str,
    root_path: str | None = None,
    allow_root_rebind: bool = False,
) -> int:
    init_schema(conn)
    row = conn.execute(
        "SELECT id, root_path, repository_identity FROM projects WHERE name = ?", (name,)
    ).fetchone()
    if row:
        if root_path:
            requested = canonical_root(root_path)
            requested_identity = repository_identity(Path(requested)) if Path(requested).is_dir() else None
            stored = row["root_path"]
            stored_identity = row["repository_identity"]
            if (
                stored_identity
                and requested_identity
                and not _repository_identities_match(stored_identity, requested_identity, requested)
            ):
                raise ValueError(
                    f"canonical root mismatch; repository identity mismatch for project '{name}': the requested checkout "
                    "does not match the brain's bound repository"
                )
            if stored and not same_root(stored, requested):
                old_root_exists = Path(stored).exists()
                if old_root_exists and not allow_root_rebind:
                    raise ValueError(
                        f"canonical root mismatch for project '{name}': brain is bound to '{stored}', "
                        f"but '{requested}' was requested; use an explicit root rebind only after verifying the checkout"
                    )
                conn.execute(
                    "UPDATE projects SET root_path = ?, repository_identity = ? WHERE id = ?",
                    (requested, requested_identity, row["id"]),
                )
                conn.execute("DELETE FROM repo_manifests WHERE project_id = ?", (row["id"],))
                conn.execute("DELETE FROM file_hash_cache WHERE project_id = ?", (row["id"],))
                conn.commit()
            elif not stored:
                conn.execute(
                    "UPDATE projects SET root_path = ?, repository_identity = ? WHERE id = ?",
                    (requested, requested_identity, row["id"]),
                )
                conn.commit()
            elif not stored_identity:
                conn.execute(
                    "UPDATE projects SET repository_identity = ? WHERE id = ?",
                    (requested_identity, row["id"]),
                )
                conn.commit()
        return int(row["id"])
    canonical = canonical_root(root_path) if root_path else None
    identity = repository_identity(Path(canonical)) if canonical and Path(canonical).is_dir() else None
    cur = conn.execute(
        "INSERT INTO projects(name, root_path, repository_identity, created_at) VALUES (?, ?, ?, ?)",
        (name, canonical, identity, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def init_project(conn: sqlite3.Connection, name: str, root_path: str, allow_root_rebind: bool = False) -> dict:
    project_id = ensure_project(conn, name, root_path, allow_root_rebind=allow_root_rebind)
    row = conn.execute(
        "SELECT root_path, repository_identity FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return {
        "status": "ok",
        "project": {
            "id": project_id,
            "name": name,
            "root_path": row["root_path"],
            "repository_identity": row["repository_identity"],
        },
    }


def _validate_project_settings(settings: dict) -> dict:
    unknown = set(settings) - set(DEFAULT_PROJECT_SETTINGS)
    if unknown:
        raise ValueError(f"unknown project setting(s): {', '.join(sorted(unknown))}")
    validated = {}
    if "max_file_bytes" in settings:
        value = int(settings["max_file_bytes"])
        if not 4_096 <= value <= 16_000_000:
            raise ValueError("max_file_bytes must be between 4,096 and 16,000,000")
        validated["max_file_bytes"] = value
    if "parser_adapter" in settings:
        value = str(settings["parser_adapter"]).strip().lower()
        if value not in {"auto", "regex", "tree-sitter", "lsp"}:
            raise ValueError("parser_adapter must be auto, regex, tree-sitter, or lsp")
        validated["parser_adapter"] = value
    if "lsp_command" in settings:
        validated["lsp_command"] = str(settings["lsp_command"]).strip()[:2_000]
    if "embedding_provider" in settings:
        value = str(settings["embedding_provider"]).strip().lower()
        if value not in {"none", "hash", "sentence-transformers"}:
            raise ValueError("embedding_provider must be none, hash, or sentence-transformers")
        validated["embedding_provider"] = value
    if "embedding_model" in settings:
        value = str(settings["embedding_model"]).strip()
        if not value or len(value) > 300:
            raise ValueError("embedding_model must contain between 1 and 300 characters")
        validated["embedding_model"] = value
    if "hybrid_weight" in settings:
        value = float(settings["hybrid_weight"])
        if not 0.0 <= value <= 1.0:
            raise ValueError("hybrid_weight must be between 0 and 1")
        validated["hybrid_weight"] = value
    return validated


def get_project_settings(conn: sqlite3.Connection, project: str = "default") -> dict:
    init_schema(conn)
    project_id = ensure_project(conn, project)
    settings = dict(DEFAULT_PROJECT_SETTINGS)
    for row in conn.execute("SELECT key, value_json FROM project_settings WHERE project_id = ?", (project_id,)):
        try:
            settings[row["key"]] = json.loads(row["value_json"])
        except json.JSONDecodeError:
            continue
    return settings


def update_project_settings(
    conn: sqlite3.Connection,
    project: str,
    settings: dict,
    root_path: str | None = None,
) -> dict:
    init_schema(conn)
    project_id = ensure_project(conn, project, root_path)
    validated = _validate_project_settings(settings)
    timestamp = now_iso()
    for key, value in validated.items():
        conn.execute(
            "INSERT INTO project_settings(project_id, key, value_json, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(project_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (project_id, key, json.dumps(value), timestamp),
        )
    if validated:
        conn.execute("DELETE FROM repo_manifests WHERE project_id = ?", (project_id,))
    conn.commit()
    return get_project_settings(conn, project)


def get_hash_cache_stats(conn: sqlite3.Connection, project: str = "default") -> dict:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not row:
        return {"status": "ok", "project": project, "entries": 0, "updated_at": None}
    stats = conn.execute(
        "SELECT COUNT(*) AS entries, MAX(updated_at) AS updated_at FROM file_hash_cache WHERE project_id = ?",
        (int(row["id"]),),
    ).fetchone()
    return {"status": "ok", "project": project, "entries": int(stats["entries"]), "updated_at": stats["updated_at"]}


def canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:/-]+", "-", value.lower()).strip("-")


def ensure_entity(conn: sqlite3.Connection, project_id: int, entity_type: str, name: str) -> int:
    key = canonical(name)
    row = conn.execute(
        "SELECT id FROM entities WHERE project_id = ? AND type = ? AND canonical_key = ?",
        (project_id, entity_type, key),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO entities(project_id, type, name, canonical_key, created_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, entity_type, name, key, now_iso()),
    )
    return int(cur.lastrowid)


def add_edge(
    conn: sqlite3.Connection,
    project_id: int,
    from_id: int,
    relation: str,
    to_id: int,
    source_id: int | None = None,
    memory_id: int | None = None,
    confidence: float = 1.0,
) -> bool:
    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO edges(project_id, from_entity_id, relation, to_entity_id, source_id, memory_id, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, from_id, relation, to_id, source_id, memory_id, confidence, now_iso()),
    )
    return conn.total_changes > before


def validate_provenance(provenance: dict | None) -> dict:
    provenance = provenance or {}
    allowed = {"source_path", "source_hash", "command", "timestamp", "verification_status", "metadata"}
    unknown = set(provenance) - allowed
    if unknown:
        raise ValueError(f"unknown provenance field(s): {', '.join(sorted(unknown))}")
    status = str(provenance.get("verification_status") or "unverified").strip().lower()
    if status not in {"unverified", "verified", "failed", "stale"}:
        raise ValueError("verification_status must be unverified, verified, failed, or stale")
    normalized = {
        "source_path": str(provenance.get("source_path") or "").strip()[:4_000] or None,
        "source_hash": str(provenance.get("source_hash") or "").strip()[:256] or None,
        "command": str(provenance.get("command") or "").strip()[:8_000] or None,
        "timestamp": str(provenance.get("timestamp") or now_iso()).strip()[:100],
        "verification_status": status,
        "metadata": provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {},
    }
    return normalized


def attach_memory_provenance(row: dict) -> dict | None:
    timestamp = row.pop("provenance_timestamp", None)
    source_path = row.pop("provenance_source_path", None)
    source_hash = row.pop("provenance_source_hash", None)
    command = row.pop("provenance_command", None)
    verification_status = row.pop("provenance_verification_status", None)
    metadata_json = row.pop("provenance_metadata_json", None)
    if not any((timestamp, source_path, source_hash, command, verification_status, metadata_json)):
        row["provenance"] = None
        return None
    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    provenance = {
        "source_path": source_path,
        "source_hash": source_hash,
        "command": command,
        "timestamp": timestamp,
        "verification_status": verification_status or "unverified",
        "metadata": metadata,
    }
    row["provenance"] = provenance
    return provenance


def remember(
    conn: sqlite3.Connection,
    text: str,
    project: str = "default",
    memory_type: str = "fact",
    pramana: str = "smriti",
    confidence: float = 0.75,
    priority: int = 5,
    metadata: dict | None = None,
    provenance: dict | None = None,
    _project_id: int | None = None,
    _commit: bool = True,
    _initialize: bool = True,
) -> dict:
    if _initialize:
        init_schema(conn)
    text = str(text).strip()
    if not text:
        raise ValueError("memory text must not be empty")
    if len(text) > 20_000:
        raise ValueError("memory text exceeds the 20,000 character limit")
    if pramana not in VALID_PRAMANA:
        raise ValueError(f"invalid pramana '{pramana}', expected one of {sorted(VALID_PRAMANA)}")
    confidence = max(0.0, min(1.0, float(confidence)))
    priority = max(1, min(10, int(priority)))
    project_id = _project_id if _project_id is not None else ensure_project(conn, project)
    provenance_input = dict(provenance or {})
    if provenance_input.get("source_path") and not provenance_input.get("source_hash"):
        project_row = conn.execute("SELECT root_path FROM projects WHERE id = ?", (project_id,)).fetchone()
        source_path = Path(str(provenance_input["source_path"])).expanduser()
        if not source_path.is_absolute() and project_row and project_row["root_path"]:
            source_path = Path(project_row["root_path"]) / source_path
        try:
            resolved_source = source_path.resolve(strict=True)
            if project_row and project_row["root_path"]:
                resolved_source.relative_to(Path(project_row["root_path"]).resolve())
            source_text = read_text(resolved_source, max_bytes=16_000_000)
            if source_text is not None:
                provenance_input["source_hash"] = sha256_text(source_text)
        except (OSError, ValueError):
            pass
    timestamp = now_iso()
    cur = conn.execute(
        """
        INSERT INTO memories(project_id, type, pramana, text, confidence, priority, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, memory_type, pramana, text, float(confidence), int(priority), json.dumps(metadata or {}), timestamp, timestamp),
    )
    memory_id = int(cur.lastrowid)
    normalized_provenance = validate_provenance(provenance_input)
    conn.execute(
        """
        INSERT INTO memory_provenance(
            memory_id, source_path, source_hash, command, timestamp, verification_status, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            normalized_provenance["source_path"],
            normalized_provenance["source_hash"],
            normalized_provenance["command"],
            normalized_provenance["timestamp"],
            normalized_provenance["verification_status"],
            json.dumps(normalized_provenance["metadata"]),
        ),
    )
    conn.execute(
        "INSERT INTO memory_fts(memory_id, project_id, text, type, pramana) VALUES (?, ?, ?, ?, ?)",
        (memory_id, project_id, text, memory_type, pramana),
    )
    memory_entity = ensure_entity(conn, project_id, "memory", f"memory:{memory_id}")
    for term in extract_terms(text):
        term_entity = ensure_entity(conn, project_id, "concept", term)
        add_edge(conn, project_id, memory_entity, "mentions", term_entity, memory_id=memory_id, confidence=0.7)
    if _commit:
        conn.commit()
    return {
        "status": "ok",
        "memory": {
            "id": memory_id,
            "project": project,
            "type": memory_type,
            "pramana": pramana,
            "confidence": float(confidence),
            "priority": int(priority),
            "text": text,
            "provenance": normalized_provenance,
        },
    }


def remember_many(conn: sqlite3.Connection, items: list[dict], project: str = "default") -> dict:
    """Store a provenance-bearing memory batch atomically."""
    init_schema(conn)
    if not isinstance(items, list) or not items:
        raise ValueError("memory batch must contain at least one item")
    if len(items) > 500:
        raise ValueError("memory batch exceeds the 500 item limit")
    project_id = ensure_project(conn, project)
    memories = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each memory batch item must be an object")
            unknown = set(item) - {
                "text", "memory_type", "type", "pramana", "confidence", "priority", "metadata", "provenance"
            }
            if unknown:
                raise ValueError(f"unknown memory batch field(s): {', '.join(sorted(unknown))}")
            result = remember(
                conn,
                text=item.get("text", ""),
                project=project,
                memory_type=item.get("memory_type", item.get("type", "fact")),
                pramana=item.get("pramana", "smriti"),
                confidence=item.get("confidence", 0.75),
                priority=item.get("priority", 5),
                metadata=item.get("metadata"),
                provenance=item.get("provenance"),
                _project_id=project_id,
                _commit=False,
                _initialize=False,
            )
            memories.append(result["memory"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"status": "ok", "project": project, "stored": len(memories), "memories": memories}


def save_checkpoint(
    conn: sqlite3.Connection,
    project: str,
    objective: str,
    verified_evidence: str = "",
    remaining_gaps: str = "",
    next_action: str = "",
    prohibited_repetition: str = "",
    expected_version: int | None = None,
    source: str = "operator",
    trigger: str = "manual",
    session_id: str | None = None,
    _commit: bool = True,
) -> dict:
    init_schema(conn)
    values = {
        "objective": str(objective).strip(),
        "verified_evidence": str(verified_evidence).strip(),
        "remaining_gaps": str(remaining_gaps).strip(),
        "next_action": str(next_action).strip(),
        "prohibited_repetition": str(prohibited_repetition).strip(),
    }
    if not values["objective"]:
        raise ValueError("checkpoint objective must not be empty")
    for key, value in values.items():
        if len(value) > 20_000:
            raise ValueError(f"checkpoint {key} exceeds the 20,000 character limit")
    project_id = ensure_project(conn, project)
    source = str(source).strip() or "operator"
    trigger = str(trigger).strip() or "manual"
    session_id = str(session_id).strip() if session_id else None
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT version FROM checkpoints WHERE project_id = ? ORDER BY version DESC, id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        current_version = int(current["version"]) if current else 0
        if expected_version is not None and int(expected_version) != current_version:
            raise ValueError(
                f"checkpoint version conflict: expected {int(expected_version)}, current version is {current_version}"
            )
        version = current_version + 1
        timestamp = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO checkpoints(
                project_id, objective, verified_evidence, remaining_gaps, next_action,
                prohibited_repetition, source, trigger, session_id, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, values["objective"], values["verified_evidence"], values["remaining_gaps"],
                values["next_action"], values["prohibited_repetition"], source, trigger, session_id,
                version, timestamp, timestamp,
            ),
        )
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "status": "ok",
        "project": project,
        "checkpoint": {
            "id": int(cursor.lastrowid), **values, "source": source, "trigger": trigger,
            "session_id": session_id, "version": version,
            "created_at": timestamp, "updated_at": timestamp,
        },
    }


def latest_checkpoint(conn: sqlite3.Connection, project: str = "default") -> dict | None:
    init_schema(conn)
    row = conn.execute(
        """
        SELECT c.id, c.objective, c.verified_evidence, c.remaining_gaps, c.next_action,
               c.prohibited_repetition, c.source, c.trigger, c.session_id,
               c.version, c.created_at, c.updated_at
        FROM checkpoints c
        JOIN projects p ON p.id = c.project_id
        WHERE p.name = ?
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT 1
        """,
        (project,),
    ).fetchone()
    return dict(row) if row else None


def _collect_json_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_collect_json_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for key in ("message", "content", "text", "body", "output", "summary"):
            if key in value:
                strings.extend(_collect_json_strings(value[key]))
        if strings:
            return strings
        for item in value.values():
            strings.extend(_collect_json_strings(item))
        return strings
    return []


def _read_thread_text(path: Path, *, root: Path | None = None) -> str:
    raw = read_text(path, MAX_THREAD_BYTES, root=root)
    if raw is None:
        raise ValueError("thread input is linked, oversized, outside its root, or changed while being read")
    if path.suffix.lower() == ".jsonl":
        parts = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                parts.append(line.strip())
            else:
                parts.extend(_collect_json_strings(payload))
        return "\n\n".join(part.strip() for part in parts if part and part.strip())
    return raw


def _candidate_memory_type(text: str) -> str | None:
    lowered = text.lower()
    if "verification evidence" in lowered or "pytest passed" in lowered or "test passed" in lowered:
        return "evidence"
    if lowered.startswith("decision:") or "we decided" in lowered:
        return "decision"
    if " must " in f" {lowered} " or " should " in f" {lowered} ":
        return "constraint"
    return None


def ingest_thread(
    conn: sqlite3.Connection,
    path: Path,
    project: str = "default",
    title: str | None = None,
    *,
    root: Path | None = None,
) -> dict:
    init_schema(conn)
    path = path.resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"thread path does not exist or is not a file: {path}")
    text = _read_thread_text(path, root=root)
    thread_hash = sha256_text(text)
    project_id = ensure_project(conn, project)
    source_title = title or path.name
    source_id = upsert_source(
        conn,
        project_id,
        "thread",
        str(path),
        source_title,
        thread_hash,
        {"title": source_title, "suffix": path.suffix.lower()},
    )
    conn.execute("DELETE FROM chunk_fts WHERE source_id = ?", (source_id,))
    conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    chunks = chunk_text(text, max_chars=2400)
    for ordinal, chunk in enumerate(chunks):
        cur = conn.execute(
            "INSERT INTO chunks(source_id, ordinal, text, hash) VALUES (?, ?, ?, ?)",
            (source_id, ordinal, chunk, sha256_text(chunk)),
        )
        conn.execute(
            "INSERT INTO chunk_fts(chunk_id, source_id, project_id, path, text) VALUES (?, ?, ?, ?, ?)",
            (int(cur.lastrowid), source_id, project_id, source_title, chunk),
        )
    promoted = 0
    prior_ids = []
    for row in conn.execute("SELECT id, metadata_json FROM memories WHERE project_id = ? AND status IN ('active', 'pinned')", (project_id,)):
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if metadata.get("source") == "ingest-thread" and metadata.get("source_path") == str(path):
            prior_ids.append(int(row["id"]))
    for memory_id in prior_ids:
        conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        conn.execute("UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?", (now_iso(), memory_id))
    for paragraph in re.split(r"\n\s*\n|(?<=\.)\s+", text):
        candidate = paragraph.strip()
        if len(candidate) < 24:
            continue
        classification = _candidate_memory_type(candidate)
        if not classification:
            continue
        memory_type = classification
        remember(
            conn,
            candidate[:1000],
            project=project,
            memory_type=memory_type,
            pramana="smriti",
            confidence=0.55,
            priority=4,
            metadata={"source": "ingest-thread", "source_path": str(path), "source_title": source_title, "verified": False},
            provenance={
                "source_path": str(path),
                "source_hash": thread_hash,
                "verification_status": "unverified",
                "metadata": {"source_title": source_title, "source_kind": "thread"},
            },
        )
        promoted += 1
        if promoted >= MAX_THREAD_PROMOTIONS:
            break
    conn.commit()
    return {
        "status": "ok",
        "project": project,
        "path": str(path),
        "title": source_title,
        "chunks": len(chunks),
        "promoted_memories": promoted,
    }


def upsert_source(conn: sqlite3.Connection, project_id: int, kind: str, path: str, title: str, hash_value: str, metadata: dict) -> int:
    timestamp = now_iso()
    row = conn.execute(
        "SELECT id FROM sources WHERE project_id = ? AND kind = ? AND path = ?",
        (project_id, kind, path),
    ).fetchone()
    if row:
        source_id = int(row["id"])
        conn.execute(
            "UPDATE sources SET title = ?, hash = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
            (title, hash_value, json.dumps(metadata), timestamp, source_id),
        )
        conn.execute("DELETE FROM chunk_fts WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        return source_id
    cur = conn.execute(
        """
        INSERT INTO sources(project_id, kind, path, title, hash, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, kind, path, title, hash_value, json.dumps(metadata), timestamp, timestamp),
    )
    return int(cur.lastrowid)


def _repo_stat_manifest(root: Path, max_file_bytes: int = 512_000) -> tuple[str, list[tuple[Path, object]], list[dict[str, str]]]:
    rejected: list[dict[str, str]] = []
    path_stats = [(path, path.stat()) for path in walk_repo(root, rejected=rejected, max_file_bytes=max_file_bytes)]
    manifest_lines = [
        f"{path.relative_to(root).as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}"
        for path, stat in path_stats
    ]
    manifest_lines.extend(f"!{item['path']}\0{item['reason']}" for item in rejected)
    return sha256_text("\n".join(manifest_lines)), path_stats, rejected


def _configured_manifest_digest(file_digest: str, settings: dict, parser_registry: ParserRegistry) -> str:
    parser_adapter = str(settings["parser_adapter"])
    parser_capability = parser_registry.capabilities().get(parser_adapter, {"available": False})
    provider_name = str(settings["embedding_provider"])
    embedding_model = {
        "none": "none",
        "hash": "rta-feature-hash-v1",
    }.get(provider_name, str(settings["embedding_model"]))
    return sha256_text(json.dumps({
        "files": file_digest,
        "max_file_bytes": int(settings["max_file_bytes"]),
        "parser_adapter": parser_adapter,
        "parser_available": parser_capability["available"],
        "lsp_command": settings["lsp_command"],
        "embedding_provider": provider_name,
        "embedding_model": embedding_model,
    }, sort_keys=True))


def _changed_path_keys(root: Path, changed_paths) -> set[str]:
    keys: set[str] = set()
    for raw_path in changed_paths or ():
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        lexical_absolute = Path(os.path.abspath(candidate))
        try:
            _lexical_root_for_candidate(root, lexical_absolute)
        except (OSError, ValueError) as exc:
            raise ValueError(f"changed path is outside the repository root: {lexical_absolute}") from exc
        absolute = lexical_absolute.resolve(strict=False)
        try:
            absolute.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"changed path is outside the repository root: {absolute}") from exc
        keys.add(os.path.normcase(str(absolute)))
    return keys


def _ingest_repo_impl(
    conn: sqlite3.Connection,
    root: Path,
    project: str = "default",
    force: bool = False,
    repair_deep_stale: bool = False,
    allow_root_rebind: bool = False,
    changed_paths=None,
) -> dict:
    init_schema(conn)
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repo path does not exist or is not a directory: {root}")
    if force and repair_deep_stale:
        raise ValueError("force and repair_deep_stale are mutually exclusive")
    project_id = ensure_project(conn, project, str(root), allow_root_rebind=allow_root_rebind)
    changed_path_keys = _changed_path_keys(root, changed_paths)
    settings = get_project_settings(conn, project)
    max_file_bytes = int(settings["max_file_bytes"])
    parser_adapter = str(settings["parser_adapter"])
    embedding_provider_name = str(settings["embedding_provider"])
    embedding_model = str(settings["embedding_model"])
    provider = create_provider(embedding_provider_name, embedding_model)
    parser_registry = ParserRegistry(load_entry_points=False, lsp_command=str(settings["lsp_command"]))
    manifest_digest, path_stats, rejected = _repo_stat_manifest(root, max_file_bytes=max_file_bytes)
    manifest_digest = _configured_manifest_digest(manifest_digest, settings, parser_registry)
    blocked_files = sum(item["reason"].startswith("oversized:") for item in rejected)
    prior_manifest = conn.execute("SELECT digest, file_count FROM repo_manifests WHERE project_id = ?", (project_id,)).fetchone()
    embedding_index_ready = True
    if provider is not None:
        expected = int(conn.execute(
            "SELECT COUNT(*) AS count FROM chunks c JOIN sources s ON s.id = c.source_id "
            "WHERE s.project_id = ? AND s.kind = 'file'", (project_id,),
        ).fetchone()["count"])
        actual = int(conn.execute(
            "SELECT COUNT(*) AS count FROM chunk_embeddings WHERE project_id = ? AND provider = ? AND model = ?",
            (project_id, provider.name, provider.model),
        ).fetchone()["count"])
        embedding_index_ready = expected == actual
    if (
        not force and not repair_deep_stale and not changed_path_keys and embedding_index_ready and prior_manifest
        and prior_manifest["digest"] == manifest_digest and int(prior_manifest["file_count"]) == len(path_stats)
    ):
        return {
            "status": "ok", "project": project, "root": str(root), "indexed_files": len(path_stats),
            "updated_files": 0, "unchanged_files": len(path_stats), "removed_files": 0,
            "skipped_files": len(rejected), "blocked_files": blocked_files, "max_file_bytes": max_file_bytes,
            "symbols": 0, "edges": 0, "chunks": 0, "embedded_chunks": 0,
            "parser_adapter": parser_adapter, "embedding_provider": embedding_provider_name,
            "parser_warnings": [], "manifest_unchanged": True,
        }
    conn.execute("BEGIN IMMEDIATE")
    existing = {str(row["path"]): dict(row) for row in conn.execute(
        "SELECT id, path, title, hash, metadata_json, updated_at FROM sources WHERE project_id = ? AND kind = 'file'",
        (project_id,),
    )}
    seen_paths = set()
    indexed_files = 0
    updated_files = 0
    unchanged_files = 0
    removed_files = 0
    skipped_files = len(rejected)
    symbols = 0
    edges = 0
    chunks = 0
    embedded_chunks = 0
    parser_warnings = []
    for path, stat in path_stats:
        file_max_bytes = effective_file_limit(root, path, max_file_bytes)
        path_key = str(path)
        path_changed = os.path.normcase(path_key) in changed_path_keys
        seen_paths.add(path_key)
        row = existing.get(path_key)
        prior_metadata = {}
        if row:
            try:
                prior_metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                prior_metadata = {}
            embedding_ready = provider is None or not bool(conn.execute(
                "SELECT 1 FROM chunks c LEFT JOIN chunk_embeddings ce ON ce.chunk_id = c.id "
                "AND ce.project_id = ? AND ce.provider = ? AND ce.model = ? "
                "WHERE c.source_id = ? AND ce.chunk_id IS NULL LIMIT 1",
                (project_id, provider.name if provider else "", provider.model if provider else "", int(row["id"])),
            ).fetchone())
            indexed_parser = prior_metadata.get("parser", "regex")
            parser_ready = indexed_parser == parser_adapter or (
                parser_adapter == "auto" and str(indexed_parser).startswith("auto:")
            )
            if repair_deep_stale:
                text = read_text(path, max_bytes=file_max_bytes)
                current_hash = sha256_text(text) if text is not None else ""
                if current_hash:
                    conn.execute(
                        "INSERT INTO file_hash_cache(project_id, path, size, mtime_ns, sha256, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(project_id, path) DO UPDATE SET size = excluded.size, mtime_ns = excluded.mtime_ns, "
                        "sha256 = excluded.sha256, updated_at = excluded.updated_at",
                        (project_id, path_key, stat.st_size, stat.st_mtime_ns, current_hash, now_iso()),
                    )
                if current_hash == row["hash"] and parser_ready and embedding_ready:
                    indexed_files += 1
                    unchanged_files += 1
                    continue
            if not force and not repair_deep_stale and not path_changed and prior_metadata.get("mtime_ns") == stat.st_mtime_ns and prior_metadata.get("size") == stat.st_size and parser_ready and embedding_ready:
                indexed_files += 1
                unchanged_files += 1
                continue
            if not force and not repair_deep_stale and not path_changed and "mtime_ns" not in prior_metadata:
                try:
                    indexed_at = datetime.fromisoformat(row["updated_at"]).timestamp()
                except (TypeError, ValueError):
                    indexed_at = 0
                if stat.st_mtime <= indexed_at:
                    indexed_files += 1
                    unchanged_files += 1
                    continue
            text = read_text(path, max_bytes=file_max_bytes)
            if not force and not repair_deep_stale and not path_changed and text is not None and sha256_text(text) == row["hash"] and parser_ready and embedding_ready:
                if "mtime_ns" in prior_metadata:
                    metadata = {**prior_metadata, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
                    conn.execute("UPDATE sources SET metadata_json = ?, updated_at = ? WHERE id = ?", (json.dumps(metadata), now_iso(), int(row["id"])))
                indexed_files += 1
                unchanged_files += 1
                continue
        record = build_file_record(
            root, path, max_bytes=file_max_bytes, parser_name=parser_adapter,
            lsp_command=str(settings["lsp_command"]), parser_registry=parser_registry,
        )
        if record is None:
            skipped_files += 1
            continue
        if row:
            conn.execute("DELETE FROM edges WHERE project_id = ? AND source_id = ?", (project_id, int(row["id"])))
        source_id = upsert_source(
            conn,
            project_id,
            "file",
            str(record.path),
            record.relative_path,
            record.sha256,
            {
                "relative_path": record.relative_path, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
                "parser": record.parser, "parser_warnings": list(record.parser_warnings),
            },
        )
        parser_warnings.extend(f"{record.relative_path}: {warning}" for warning in record.parser_warnings)
        file_entity = ensure_entity(conn, project_id, "file", record.relative_path)
        vectors = provider.embed(record.chunks) if provider is not None else []
        for ordinal, chunk in enumerate(record.chunks):
            cur = conn.execute(
                "INSERT INTO chunks(source_id, ordinal, text, hash) VALUES (?, ?, ?, ?)",
                (source_id, ordinal, chunk, sha256_text(chunk)),
            )
            chunk_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO chunk_fts(chunk_id, source_id, project_id, path, text) VALUES (?, ?, ?, ?, ?)",
                (chunk_id, source_id, project_id, record.relative_path, chunk),
            )
            if provider is not None:
                vector = vectors[ordinal]
                conn.execute(
                    "INSERT INTO chunk_embeddings(project_id, chunk_id, provider, model, vector_json, content_hash, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (project_id, chunk_id, provider.name, provider.model, json.dumps(vector), sha256_text(chunk), now_iso()),
                )
                embedded_chunks += 1
            chunks += 1
        for symbol in record.symbols:
            sym_entity = ensure_entity(conn, project_id, "symbol", symbol)
            if add_edge(conn, project_id, file_entity, "contains", sym_entity, source_id=source_id):
                edges += 1
            symbols += 1
        for imported in record.imports:
            import_entity = ensure_entity(conn, project_id, "import", imported)
            if add_edge(conn, project_id, file_entity, "imports", import_entity, source_id=source_id):
                edges += 1
        for called in record.calls:
            call_entity = ensure_entity(conn, project_id, "call", called)
            if add_edge(conn, project_id, file_entity, "calls", call_entity, source_id=source_id, confidence=0.55):
                edges += 1
        indexed_files += 1
        updated_files += 1
        conn.execute(
            "INSERT INTO file_hash_cache(project_id, path, size, mtime_ns, sha256, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(project_id, path) DO UPDATE SET size = excluded.size, mtime_ns = excluded.mtime_ns, "
            "sha256 = excluded.sha256, updated_at = excluded.updated_at",
            (project_id, path_key, stat.st_size, stat.st_mtime_ns, record.sha256, now_iso()),
        )
    for path_key, row in existing.items():
        if path_key in seen_paths:
            continue
        source_id = int(row["id"])
        conn.execute("DELETE FROM chunk_fts WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM edges WHERE project_id = ? AND source_id = ?", (project_id, source_id))
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        conn.execute("DELETE FROM file_hash_cache WHERE project_id = ? AND path = ?", (project_id, path_key))
        removed_files += 1
    if updated_files or removed_files:
        call_rows = conn.execute(
            """
            SELECT e.from_entity_id AS file_id, e.source_id, c.canonical_key,
                   s.id AS symbol_id, f.name AS file_name
            FROM edges e
            JOIN entities c ON c.id = e.to_entity_id AND c.type = 'call'
            JOIN entities f ON f.id = e.from_entity_id AND f.type = 'file'
            JOIN entities s ON s.project_id = e.project_id AND s.type = 'symbol'
                AND s.canonical_key = c.canonical_key
            WHERE e.project_id = ? AND e.relation = 'calls'
            ORDER BY e.id, s.id
            """,
            (project_id,),
        ).fetchall()
        for call in call_rows:
            normalized = str(call["file_name"]).casefold().replace("\\", "/")
            is_test = (
                normalized.startswith("test_") or "/test_" in normalized
                or "/tests/" in f"/{normalized}" or ".test." in normalized or ".spec." in normalized
            )
            relation = "tests" if is_test else "calls"
            confidence = 0.7 if is_test else 0.8
            if add_edge(
                conn, project_id, int(call["file_id"]), relation, int(call["symbol_id"]),
                source_id=int(call["source_id"]), confidence=confidence,
            ):
                edges += 1
        conn.execute(
            "DELETE FROM entities WHERE project_id = ? AND type IN ('file', 'symbol', 'import', 'call') "
            "AND NOT EXISTS (SELECT 1 FROM edges WHERE from_entity_id = entities.id OR to_entity_id = entities.id)",
            (project_id,),
        )
    conn.execute("DELETE FROM entities WHERE project_id = ? AND canonical_key = ''", (project_id,))
    conn.execute(
        "INSERT INTO repo_manifests(project_id, digest, file_count, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(project_id) DO UPDATE SET digest = excluded.digest, file_count = excluded.file_count, updated_at = excluded.updated_at",
        (project_id, manifest_digest, len(path_stats), now_iso()),
    )
    conn.commit()
    return {
        "status": "ok", "project": project, "root": str(root), "indexed_files": indexed_files,
        "updated_files": updated_files, "unchanged_files": unchanged_files, "removed_files": removed_files,
        "skipped_files": skipped_files, "blocked_files": blocked_files, "max_file_bytes": max_file_bytes,
        "symbols": symbols, "edges": edges, "chunks": chunks, "embedded_chunks": embedded_chunks,
        "parser_adapter": parser_adapter, "embedding_provider": embedding_provider_name,
        "parser_warnings": parser_warnings[:100], "manifest_unchanged": False,
        "verified_changed_paths": len(changed_path_keys),
        "deep_stale_repair": bool(repair_deep_stale),
    }


def ingest_repo(
    conn: sqlite3.Connection,
    root: Path,
    project: str = "default",
    force: bool = False,
    repair_deep_stale: bool = False,
    allow_root_rebind: bool = False,
    changed_paths=None,
) -> dict:
    """Refresh a repository atomically so failed parses never leak a partial index."""
    try:
        return _ingest_repo_impl(
            conn,
            root,
            project=project,
            force=force,
            repair_deep_stale=repair_deep_stale,
            allow_root_rebind=allow_root_rebind,
            changed_paths=changed_paths,
        )
    except Exception:
        conn.rollback()
        raise


def query_to_fts(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    if not tokens:
        return '""'
    meaningful = []
    seen = set()
    for token in tokens:
        lowered = token.lower()
        if lowered in QUERY_STOP_WORDS or lowered in seen:
            continue
        seen.add(lowered)
        meaningful.append(token)
    selected = meaningful or tokens[:4]
    return " OR ".join(selected[:8])


_CONSEQUENTIAL_SOURCE_TERMS = {
    "active",
    "architecture",
    "authority",
    "canonical",
    "complete",
    "completion",
    "current",
    "goal",
    "incomplete",
    "launch",
    "objective",
    "remaining",
    "source",
    "status",
    "truth",
}

_SOURCE_INTENT_TERMS = {
    "architecture",
    "drift",
    "filesystem",
    "formulations",
    "implements",
    "ledger",
    "loom",
    "mathematical",
    "mathematics",
    "skill",
    "skills",
    "structure",
    "workbench",
}


def _is_consequential_source_query(query: str) -> bool:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", query)}
    return bool(
        len(tokens & _CONSEQUENTIAL_SOURCE_TERMS) >= 2
        or ("source" in tokens and tokens & _SOURCE_INTENT_TERMS)
    )


def _source_authority_score(path: str, query: str) -> int:
    """Prefer current source contracts over tests and packaged historical copies.

    The score is deliberately path- and intent-based. It does not claim that a
    retrieved excerpt is true; it only makes the most likely canonical source
    easier to verify first for consequential project-state questions.
    """

    if not _is_consequential_source_query(query):
        return 0
    normalized = str(path or "").replace("\\", "/").lower()
    basename = normalized.rsplit("/", 1)[-1]
    query_tokens = {
        token.lower() for token in re.findall(r"[A-Za-z0-9_]+", query)
    }
    score = 0
    if normalized.startswith("00_source_of_truth/") or "/00_source_of_truth/" in normalized:
        score += 60
    if (
        "live_context" in basename
        and query_tokens & {"current", "status", "remaining", "active", "latest"}
        and not query_tokens & {"goal", "objective", "completion"}
    ):
        score += 90
    if "active_goal" in basename and query_tokens & {"goal", "objective", "complete", "completion", "incomplete"}:
        score += 120
        version_match = re.search(r"_v(\d+)(?:\.[^/]*)?\.md$", basename)
        if version_match:
            score += min(25, int(version_match.group(1)))
    if query_tokens & {"skill", "skills", "drift"} and basename == "agents.md":
        score += 280
    if basename in {"agents.md", "architecture.md", "readme.md"}:
        score += 20
    if normalized.startswith("03_tests/") or "/03_tests/" in normalized or "/tests/" in normalized:
        score -= 90
    if normalized.startswith("04_deployment/") or "/04_deployment/" in normalized:
        score -= 55
    if "__pycache__" in normalized or normalized.endswith((".pyc", ".pyo")):
        score -= 120
    return score


def search(
    conn: sqlite3.Connection,
    query: str,
    project: str | None = None,
    limit: int = 8,
    hybrid: bool | None = None,
    *,
    record_recall: bool = True,
    _initialize: bool = True,
) -> dict:
    if _initialize:
        init_schema(conn)
    query = str(query)[:10_000]
    limit = max(1, min(MAX_SEARCH_LIMIT, int(limit)))
    fts_query = query_to_fts(query)
    project_id = None
    if project:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
        if not row:
            return {
                "status": "ok", "query": query, "memories": [], "chunks": [],
                "retrieval": {"mode": "fts", "provider": "none"},
            }
        project_id = int(row["id"])
    if project and _initialize:
        settings = get_project_settings(conn, project)
    elif project_id is not None:
        settings = dict(DEFAULT_PROJECT_SETTINGS)
        for setting in conn.execute(
            "SELECT key, value_json FROM project_settings WHERE project_id = ?", (project_id,),
        ):
            try:
                settings[setting["key"]] = json.loads(setting["value_json"])
            except json.JSONDecodeError:
                continue
    else:
        settings = dict(DEFAULT_PROJECT_SETTINGS)
    provider_name = str(settings["embedding_provider"])
    use_hybrid = (provider_name != "none") if hybrid is None else bool(hybrid and provider_name != "none")
    project_count = int(conn.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"])
    consequential_source_query = _is_consequential_source_query(query)
    candidate_limit = (
        min(5000, max(512, limit * 64))
        if project_count > 1 or consequential_source_query
        else limit
    )

    memory_candidates = conn.execute(
        """
        SELECT memory_id, project_id, bm25(memory_fts) AS rank
        FROM memory_fts
        WHERE memory_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, max(64, candidate_limit)),
    ).fetchall()
    selected_memories = [
        row for row in memory_candidates
        if project_id is None or int(row["project_id"]) == project_id
    ][:limit]
    memories = []
    if selected_memories:
        memory_ids = [int(row["memory_id"]) for row in selected_memories]
        placeholders = ",".join("?" for _ in memory_ids)
        rows_by_id = {
            int(row["id"]): dict(row)
            for row in conn.execute(
                f"""
                SELECT m.id, p.name AS project, m.type, m.pramana, m.text, m.confidence,
                       m.priority, m.status, m.metadata_json,
                       mp.source_path AS provenance_source_path,
                       mp.source_hash AS provenance_source_hash,
                       mp.command AS provenance_command,
                       mp.timestamp AS provenance_timestamp,
                       mp.verification_status AS provenance_verification_status,
                       mp.metadata_json AS provenance_metadata_json
                FROM memories m
                JOIN projects p ON p.id = m.project_id
                LEFT JOIN memory_provenance mp ON mp.memory_id = m.id
                WHERE m.id IN ({placeholders}) AND m.status IN ('active', 'pinned')
                """,
                memory_ids,
            )
        }
        for candidate in selected_memories:
            item = rows_by_id.get(int(candidate["memory_id"]))
            if item:
                attach_memory_provenance(item)
                item["rank"] = candidate["rank"]
                memories.append(item)

    chunk_candidates = conn.execute(
        """
        SELECT chunk_id, project_id, path, bm25(chunk_fts) AS rank
        FROM chunk_fts
        WHERE chunk_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, candidate_limit),
    ).fetchall()
    project_chunks = [
        row for row in chunk_candidates
        if project_id is None or int(row["project_id"]) == project_id
    ]
    if consequential_source_query and project_id is not None:
        canonical_candidates = conn.execute(
            """
            SELECT c.id AS chunk_id, s.project_id, s.title AS path, 1000000.0 AS rank
            FROM sources s
            JOIN chunks c ON c.source_id = s.id AND c.ordinal = 0
            WHERE s.project_id = ?
              AND (
                lower(s.title) LIKE '00_source_of_truth/%'
                OR lower(s.title) IN ('agents.md', 'architecture.md', 'readme.md')
                OR lower(s.title) LIKE '%live_context%.md'
                OR lower(s.title) LIKE '%active_goal%'
              )
            LIMIT 5000
            """,
            (project_id,),
        ).fetchall()
        by_chunk_id = {int(row["chunk_id"]): row for row in project_chunks}
        for row in canonical_candidates:
            if _source_authority_score(str(row["path"] or ""), query) > 0:
                by_chunk_id.setdefault(int(row["chunk_id"]), row)
        project_chunks = list(by_chunk_id.values())
    if consequential_source_query:
        project_chunks = sorted(
            project_chunks,
            key=lambda row: (
                -_source_authority_score(str(row["path"] or ""), query),
                float(row["rank"]),
                str(row["path"] or ""),
            ),
        )
    selected_chunks = project_chunks[:limit]
    chunks = []
    if selected_chunks:
        chunk_ids = [int(row["chunk_id"]) for row in selected_chunks]
        placeholders = ",".join("?" for _ in chunk_ids)
        rows_by_id = {
            int(row["id"]): dict(row)
            for row in conn.execute(
                f"""
                SELECT c.id, p.name AS project, substr(c.text, 1, 500) AS text, s.hash AS source_hash
                FROM chunks c
                JOIN sources s ON s.id = c.source_id
                JOIN projects p ON p.id = s.project_id
                WHERE c.id IN ({placeholders})
                """,
                chunk_ids,
            )
        }
        for candidate in selected_chunks:
            item = rows_by_id.get(int(candidate["chunk_id"]))
            if item:
                item["path"] = candidate["path"]
                item["rank"] = candidate["rank"]
                item["source_authority_score"] = _source_authority_score(
                    str(candidate["path"] or ""), query
                )
                chunks.append(item)
    retrieval = {
        "mode": "fts",
        "provider": "none",
        "canonical_source_reranking": consequential_source_query,
    }
    if use_hybrid and project_id is not None:
        provider = create_provider(provider_name, str(settings["embedding_model"]))
        query_vector = provider.embed([query])[0]
        semantic_rows = conn.execute(
            """
            SELECT ce.chunk_id, ce.vector_json, c.text, s.hash AS source_hash, s.title AS path, p.name AS project
            FROM chunk_embeddings ce
            JOIN chunks c ON c.id = ce.chunk_id
            JOIN sources s ON s.id = c.source_id
            JOIN projects p ON p.id = ce.project_id
            WHERE ce.project_id = ? AND ce.provider = ? AND ce.model = ?
            LIMIT 5000
            """,
            (project_id, provider.name, provider.model),
        ).fetchall()
        lexical_order = {int(item["id"]): index for index, item in enumerate(chunks)}
        merged = {int(item["id"]): item for item in chunks}
        semantic_scores = {}
        for row in semantic_rows:
            try:
                vector = json.loads(row["vector_json"])
            except json.JSONDecodeError:
                continue
            chunk_id = int(row["chunk_id"])
            semantic_scores[chunk_id] = max(0.0, cosine_similarity(query_vector, vector))
            if chunk_id not in merged:
                merged[chunk_id] = {
                    "id": chunk_id, "project": row["project"], "text": str(row["text"])[:500],
                    "source_hash": row["source_hash"], "path": row["path"], "rank": None,
                }
        semantic_weight = float(settings["hybrid_weight"])
        for chunk_id, item in merged.items():
            lexical_score = 1.0 / (1.0 + lexical_order[chunk_id]) if chunk_id in lexical_order else 0.0
            semantic_score = semantic_scores.get(chunk_id, 0.0)
            item["lexical_score"] = round(lexical_score, 6)
            item["semantic_score"] = round(semantic_score, 6)
            item["hybrid_score"] = round((1.0 - semantic_weight) * lexical_score + semantic_weight * semantic_score, 6)
        chunks = sorted(merged.values(), key=lambda item: (-item["hybrid_score"], str(item["path"])))[:limit]
        retrieval = {
            "mode": "hybrid", "provider": provider.name, "model": provider.model,
            "semantic_weight": semantic_weight, "candidates": len(merged),
        }
    selected = {"memories": [item["id"] for item in memories], "chunks": [item["id"] for item in chunks]}
    if record_recall:
        conn.execute(
            "INSERT INTO recall_logs(project_id, query, selected_json, created_at) VALUES (?, ?, ?, ?)",
            (project_id, query, json.dumps(selected), now_iso()),
        )
        conn.commit()
    return {"status": "ok", "query": query, "memories": memories, "chunks": chunks, "retrieval": retrieval}


def _memory_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contradiction_base(text: str) -> str | None:
    lowered = f" {_memory_norm(text)} "
    pairs = [
        (" fail closed ", " fail open "),
        (" enabled ", " disabled "),
        (" allow ", " deny "),
        (" allowed ", " denied "),
        (" true ", " false "),
        (" required ", " forbidden "),
    ]
    for left, right in pairs:
        if left in lowered:
            return lowered.replace(left, " <opposite> ").strip()
        if right in lowered:
            return lowered.replace(right, " <opposite> ").strip()
    return None


def reflect(conn: sqlite3.Connection, project: str = "default") -> dict:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not row:
        return {"status": "ok", "project": project, "duplicates_superseded": 0, "contradictions_flagged": 0, "active_memories": 0}
    project_id = int(row["id"])
    memories = [
        dict(item)
        for item in conn.execute(
            "SELECT id, text, confidence, priority, status FROM memories WHERE project_id = ? AND status IN ('active', 'pinned') ORDER BY priority DESC, confidence DESC, id ASC",
            (project_id,),
        )
    ]
    seen = {}
    duplicates = []
    for memory in memories:
        key = _memory_norm(memory["text"])
        if key in seen:
            duplicates.append(memory["id"])
        else:
            seen[key] = memory["id"]
    timestamp = now_iso()
    for memory_id in duplicates:
        conn.execute("UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?", (timestamp, memory_id))

    active_after_dupes = [
        dict(item)
        for item in conn.execute(
            "SELECT id, text FROM memories WHERE project_id = ? AND status IN ('active', 'pinned') ORDER BY id ASC",
            (project_id,),
        )
    ]
    bases: dict[str, list[int]] = {}
    for memory in active_after_dupes:
        base = _contradiction_base(memory["text"])
        if base:
            bases.setdefault(base, []).append(memory["id"])
    contradicted_ids = sorted({memory_id for ids in bases.values() if len(ids) > 1 for memory_id in ids})
    for memory_id in contradicted_ids:
        conn.execute("UPDATE memories SET status = 'contradicted', updated_at = ? WHERE id = ?", (timestamp, memory_id))
    conn.commit()
    active_count = conn.execute("SELECT COUNT(*) AS c FROM memories WHERE project_id = ? AND status IN ('active', 'pinned')", (project_id,)).fetchone()["c"]
    return {
        "status": "ok",
        "project": project,
        "duplicates_superseded": len(duplicates),
        "contradictions_flagged": len(contradicted_ids),
        "active_memories": active_count,
    }


def graph(conn: sqlite3.Connection, project: str = "default", limit: int = 100) -> dict:
    limit = max(1, min(MAX_GRAPH_LIMIT, int(limit)))
    schema_ready = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'projects'"
    ).fetchone()
    if not schema_ready:
        return {"status": "ok", "project": project, "nodes": [], "edges": [], "counts": {"nodes": 0, "edges": 0}}
    project_row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not project_row:
        return {"status": "ok", "project": project, "nodes": [], "edges": [], "counts": {"nodes": 0, "edges": 0}}
    project_id = int(project_row["id"])
    source_budget = max(1, (limit + 2) // 3)
    source_ids = [
        int(row["source_id"])
        for row in conn.execute(
            """
            SELECT source_id
            FROM edges
            WHERE project_id = ? AND source_id IS NOT NULL
            GROUP BY source_id
            ORDER BY source_id
            LIMIT ?
            """,
            (project_id, source_budget),
        )
    ]
    edges = []
    edge_sql = """
        SELECT e.id, e.from_entity_id AS from_id, f.name AS from_name, e.relation,
               e.to_entity_id AS to_id, t.name AS to_name, e.confidence
        FROM edges e
        JOIN entities f ON f.id = e.from_entity_id
        JOIN entities t ON t.id = e.to_entity_id
        WHERE e.project_id = ? AND e.source_id = ?
        ORDER BY e.id
        LIMIT 3
    """
    for source_id in source_ids:
        edges.extend(dict(row) for row in conn.execute(edge_sql, (project_id, source_id)))
        if len(edges) >= limit:
            break
    if len(edges) < limit:
        edges.extend(
            dict(row)
            for row in conn.execute(
                """
                SELECT e.id, e.from_entity_id AS from_id, f.name AS from_name, e.relation,
                       e.to_entity_id AS to_id, t.name AS to_name, e.confidence
                FROM edges e
                JOIN entities f ON f.id = e.from_entity_id
                JOIN entities t ON t.id = e.to_entity_id
                WHERE e.project_id = ? AND e.source_id IS NULL
                ORDER BY e.memory_id, e.id
                LIMIT ?
                """,
                (project_id, limit - len(edges)),
            )
        )
    edges = edges[:limit]
    entity_ids = sorted({int(edge[key]) for edge in edges for key in ("from_id", "to_id")})
    nodes = []
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        nodes = [dict(row) for row in conn.execute(
            f"SELECT id, type, name, canonical_key FROM entities WHERE project_id = ? AND id IN ({placeholders}) ORDER BY type, name",
            (project_id, *entity_ids),
        )]
    if len(nodes) < limit:
        excluded = {int(node["id"]) for node in nodes}
        extras = conn.execute("SELECT id, type, name, canonical_key FROM entities WHERE project_id = ? ORDER BY type, name LIMIT ?", (project_id, limit)).fetchall()
        nodes.extend(dict(row) for row in extras if int(row["id"]) not in excluded and len(nodes) < limit)
    return {"status": "ok", "project": project, "nodes": nodes, "edges": edges, "counts": {"nodes": len(nodes), "edges": len(edges)}}


def graph_query(
    conn: sqlite3.Connection,
    *,
    project: str = "default",
    query_type: str = "impact",
    target: str,
    depth: int = 2,
    limit: int = 100,
) -> dict:
    """Traverse a bounded, deterministic project subgraph around a named entity."""
    init_schema(conn)
    mode = str(query_type).strip().lower()
    if mode not in {"dependencies", "dependents", "impact", "evidence", "relevance"}:
        raise ValueError(f"unknown graph query type: {query_type}")
    target_text = str(target).strip()
    if not target_text:
        raise ValueError("graph query target is required")
    bounded_depth = max(0, min(4, int(depth)))
    bounded_limit = max(1, min(MAX_GRAPH_LIMIT, int(limit)))
    relation_filters = {
        "dependencies": ("calls", "imports"),
        "dependents": ("calls", "contains", "imports", "tests"),
        "impact": ("calls", "contains", "imports", "tests"),
        "evidence": ("contains", "mentions", "tests"),
        "relevance": ("mentions",),
    }
    allowed_relations = relation_filters[mode]
    project_row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not project_row:
        return {
            "status": "ok", "project": project, "query_type": mode, "target": target_text,
            "depth": bounded_depth, "relation_filter": list(allowed_relations),
            "nodes": [], "edges": [], "truncated": False,
        }
    project_id = int(project_row["id"])
    key = canonical(target_text)
    escaped_target = target_text.replace("%", "\\%").replace("_", "\\_")
    seed_rows = conn.execute(
        """
        SELECT id FROM entities
        WHERE project_id = ? AND canonical_key = ?
        ORDER BY type, name, id
        LIMIT 25
        """,
        (project_id, key),
    ).fetchall()
    if not seed_rows:
        seed_rows = conn.execute(
            """
            SELECT id FROM entities
            WHERE project_id = ? AND name LIKE ? ESCAPE '\\'
            ORDER BY type, name, id
            LIMIT 25
            """,
            (project_id, f"%{escaped_target}%"),
        ).fetchall()
    frontier = {int(row["id"]) for row in seed_rows}
    visited = set(frontier)
    selected_edges: dict[int, dict] = {}
    truncated = False
    for _ in range(bounded_depth):
        if not frontier or len(visited) >= bounded_limit:
            break
        placeholders = ",".join("?" for _ in frontier)
        clauses = []
        parameters: list[object] = [project_id]
        if mode in {"dependencies", "impact", "relevance"}:
            clauses.append(f"e.from_entity_id IN ({placeholders})")
            parameters.extend(sorted(frontier))
        if mode in {"dependents", "impact", "evidence", "relevance"}:
            clauses.append(f"e.to_entity_id IN ({placeholders})")
            parameters.extend(sorted(frontier))
        rows = conn.execute(
            f"""
            SELECT e.id, e.from_entity_id AS from_id, f.name AS from_name,
                   e.relation, e.to_entity_id AS to_id, t.name AS to_name,
                   e.confidence, e.source_id, e.memory_id
            FROM edges e
            JOIN entities f ON f.id = e.from_entity_id
            JOIN entities t ON t.id = e.to_entity_id
            WHERE e.project_id = ? AND ({' OR '.join(clauses)})
              AND e.relation IN ({','.join('?' for _ in allowed_relations)})
            ORDER BY e.confidence DESC, e.id
            LIMIT ?
            """,
            (*parameters, *allowed_relations, bounded_limit * 4),
        ).fetchall()
        next_frontier = set()
        for row in rows:
            edge = dict(row)
            from_id, to_id = int(edge["from_id"]), int(edge["to_id"])
            if mode == "dependencies" and from_id not in frontier:
                continue
            if mode in {"dependents", "evidence"} and to_id not in frontier:
                continue
            selected_edges[int(edge["id"])] = edge
            neighbor = to_id if from_id in frontier else from_id
            if neighbor not in visited:
                if len(visited) >= bounded_limit:
                    truncated = True
                    break
                visited.add(neighbor)
                next_frontier.add(neighbor)
        frontier = next_frontier
    nodes = []
    if visited:
        ids = sorted(visited)[:bounded_limit]
        placeholders = ",".join("?" for _ in ids)
        nodes = [dict(row) for row in conn.execute(
            f"SELECT id, type, name, canonical_key FROM entities WHERE project_id = ? AND id IN ({placeholders}) ORDER BY type, name, id",
            (project_id, *ids),
        )]
    node_ids = {int(node["id"]) for node in nodes}
    edges = [
        edge for _, edge in sorted(selected_edges.items())
        if int(edge["from_id"]) in node_ids and int(edge["to_id"]) in node_ids
    ][:bounded_limit]
    return {
        "status": "ok", "project": project, "query_type": mode, "target": target_text,
        "depth": bounded_depth, "relation_filter": list(allowed_relations), "nodes": nodes, "edges": edges,
        "truncated": truncated or len(selected_edges) > bounded_limit,
    }


def indexed_freshness(conn: sqlite3.Connection, project: str = "default") -> dict:
    """Return the freshness guaranteed by the latest completed repo ingestion.

    This deliberately avoids touching the live filesystem. Explicit stale-check
    commands remain the source of truth when current working-tree freshness matters.
    """
    init_schema(conn)
    project_row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not project_row:
        return {
            "status": "ok", "project": project, "mode": "index-snapshot", "state": "unknown",
            "fresh": 0, "changed": 0, "missing": 0, "added": 0, "details": [], "checked_at": None,
        }
    project_id = int(project_row["id"])
    source_count = int(conn.execute(
        "SELECT COUNT(*) AS count FROM sources WHERE project_id = ? AND kind = 'file'",
        (project_id,),
    ).fetchone()["count"])
    manifest = conn.execute(
        "SELECT file_count, updated_at FROM repo_manifests WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if not manifest:
        return {
            "status": "ok", "project": project, "mode": "index-snapshot", "state": "unknown",
            "fresh": source_count, "changed": 0, "missing": 0, "added": 0, "details": [], "checked_at": None,
        }
    expected_count = int(manifest["file_count"])
    mismatch = expected_count != source_count
    return {
        "status": "ok",
        "project": project,
        "mode": "index-snapshot",
        "state": "stale" if mismatch else ("fresh" if source_count else "unknown"),
        "fresh": min(source_count, expected_count),
        "changed": 0,
        "missing": max(0, expected_count - source_count),
        "added": max(0, source_count - expected_count),
        "details": [],
        "checked_at": manifest["updated_at"],
    }


def stale_check(
    conn: sqlite3.Connection,
    project: str = "default",
    deep: bool = False,
    refresh_hashes: bool = False,
    detail_limit: int = 50,
    include_fresh_details: bool = False,
) -> dict:
    init_schema(conn)
    detail_limit = max(0, min(500, int(detail_limit)))
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not row:
        return {
            "status": "ok", "project": project, "mode": "sha256" if deep else "stat-manifest",
            "state": "unknown", "fresh": 0, "changed": 0, "missing": 0, "added": 0,
            "hash_cache_hits": 0, "hash_cache_misses": 0, "details": [],
            "details_total": 0, "details_truncated": False, "fresh_details_omitted": 0,
        }
    settings = get_project_settings(conn, project)
    details = []
    counts = {"fresh": 0, "changed": 0, "missing": 0, "added": 0, "uninspectable": 0}
    indexed_titles = set()
    project_row = conn.execute("SELECT root_path FROM projects WHERE id = ?", (int(row["id"]),)).fetchone()
    root_path = Path(project_row["root_path"]).resolve() if project_row and project_row["root_path"] else None
    current_by_path = {}
    rejected: list[dict[str, str]] = []
    manifest_digest = None
    if root_path and root_path.exists():
        manifest_digest, path_stats, rejected = _repo_stat_manifest(root_path, max_file_bytes=int(settings["max_file_bytes"]))
        manifest_digest = _configured_manifest_digest(
            manifest_digest,
            settings,
            ParserRegistry(load_entry_points=False, lsp_command=str(settings["lsp_command"])),
        )
        current_by_path = {str(path): stat for path, stat in path_stats}
        if not deep:
            manifest = conn.execute("SELECT digest, file_count FROM repo_manifests WHERE project_id = ?", (int(row["id"]),)).fetchone()
            if manifest and manifest["digest"] == manifest_digest and int(manifest["file_count"]) == len(path_stats):
                rejected_details = []
                for item in rejected:
                    path = Path(item["path"])
                    try:
                        title = path.relative_to(root_path).as_posix()
                    except ValueError:
                        title = path.name
                    rejected_details.append({
                        "source_id": None,
                        "path": item["path"],
                        "title": title,
                        "status": "uninspectable",
                        "reason": item["reason"],
                    })
                compact_details = rejected_details
                if include_fresh_details:
                    compact_details = [
                        {
                            "source_id": None,
                            "path": str(path),
                            "title": path.relative_to(root_path).as_posix(),
                            "status": "fresh",
                        }
                        for path, _stat in path_stats
                    ] + rejected_details
                return {
                    "status": "ok", "project": project, "mode": "stat-manifest",
                    "state": "stale" if rejected else "fresh",
                    "fresh": len(path_stats), "changed": 0, "missing": 0, "added": 0,
                    "uninspectable": len(rejected), "hash_cache_hits": 0, "hash_cache_misses": 0,
                    "details": compact_details[:detail_limit],
                    "details_total": len(compact_details),
                    "details_truncated": len(compact_details) > detail_limit,
                    "fresh_details_omitted": 0 if include_fresh_details else len(path_stats),
                }
    hash_cache_hits = 0
    hash_cache_misses = 0
    for source in conn.execute("SELECT id, path, title, hash, metadata_json, updated_at FROM sources WHERE project_id = ? AND kind = 'file'", (int(row["id"]),)):
        path = Path(source["path"])
        indexed_titles.add(str(source["title"]).replace("\\", "/"))
        stat = current_by_path.get(str(path))
        if stat is None:
            status = "missing"
        elif deep or refresh_hashes:
            cached = conn.execute(
                "SELECT sha256 FROM file_hash_cache WHERE project_id = ? AND path = ? AND size = ? AND mtime_ns = ?",
                (int(row["id"]), str(path), stat.st_size, stat.st_mtime_ns),
            ).fetchone()
            if cached and not refresh_hashes:
                current_hash = cached["sha256"]
                hash_cache_hits += 1
            else:
                text = read_text(path, max_bytes=int(settings["max_file_bytes"]))
                current_hash = sha256_text(text) if text is not None else ""
                hash_cache_misses += 1
                if current_hash:
                    conn.execute(
                        "INSERT INTO file_hash_cache(project_id, path, size, mtime_ns, sha256, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(project_id, path) DO UPDATE SET size = excluded.size, mtime_ns = excluded.mtime_ns, "
                        "sha256 = excluded.sha256, updated_at = excluded.updated_at",
                        (int(row["id"]), str(path), stat.st_size, stat.st_mtime_ns, current_hash, now_iso()),
                    )
            status = "fresh" if current_hash == source["hash"] else "changed"
        else:
            try:
                metadata = json.loads(source["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            if metadata.get("mtime_ns") == stat.st_mtime_ns and metadata.get("size") == stat.st_size:
                status = "fresh"
            else:
                try:
                    indexed_at = datetime.fromisoformat(source["updated_at"]).timestamp()
                except (TypeError, ValueError):
                    indexed_at = 0
                status = "fresh" if stat.st_mtime <= indexed_at else "changed"
        counts[status] += 1
        if status != "fresh" or include_fresh_details:
            details.append({"source_id": source["id"], "path": source["path"], "title": source["title"], "status": status})
    if root_path and root_path.exists():
        current_titles = {path.relative_to(root_path).as_posix() for path in map(Path, current_by_path)}
        for title in sorted(current_titles - indexed_titles):
            counts["added"] += 1
            details.append({"source_id": None, "path": str(root_path / title), "title": title, "status": "added"})
        for item in rejected:
            path = Path(item["path"])
            try:
                title = path.relative_to(root_path).as_posix()
            except ValueError:
                title = path.name
            counts["uninspectable"] += 1
            details.append({
                "source_id": None,
                "path": item["path"],
                "title": title,
                "status": "uninspectable",
                "reason": item["reason"],
            })
    total = counts["fresh"] + counts["changed"] + counts["missing"]
    anomalies = counts["changed"] + counts["missing"] + counts["added"] + counts["uninspectable"]
    state = "stale" if anomalies else ("unknown" if total == 0 else "fresh")
    if deep:
        conn.commit()
    details_total = len(details)
    return {
        "status": "ok", "project": project, "mode": "sha256" if deep else "stat-manifest", "state": state,
        **counts,
        "hash_cache_hits": hash_cache_hits,
        "hash_cache_misses": hash_cache_misses,
        "details": details[:detail_limit],
        "details_total": details_total,
        "details_truncated": details_total > detail_limit,
        "fresh_details_omitted": 0 if include_fresh_details else counts["fresh"],
    }


def doctor(conn: sqlite3.Connection) -> dict:
    init_schema(conn)
    fts_enabled = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'").fetchone())
    return {
        "status": "ok",
        "sqlite_version": sqlite3.sqlite_version,
        "fts_enabled": fts_enabled,
        "projects": conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"],
        "memories": conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"],
        "sources": conn.execute("SELECT COUNT(*) AS c FROM sources").fetchone()["c"],
    }
