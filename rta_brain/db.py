import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .ingest import build_file_record, chunk_text, extract_terms, read_text, sha256_text, walk_repo


VALID_PRAMANA = {"pratyaksha", "sabda", "anumana", "smriti", "kalpana"}
MAX_THREAD_BYTES = 10 * 1024 * 1024
MAX_THREAD_PROMOTIONS = 100
MAX_SEARCH_LIMIT = 50
MAX_GRAPH_LIMIT = 500
QUERY_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "what", "when", "where", "which", "with",
    "code", "explain", "file", "files", "focused", "next", "prepare",
    "safest", "step", "task",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            root_path TEXT,
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
        """
    )
    conn.commit()


def ensure_project(conn: sqlite3.Connection, name: str, root_path: str | None = None) -> int:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        if root_path:
            conn.execute("UPDATE projects SET root_path = ? WHERE id = ?", (root_path, row["id"]))
            conn.commit()
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO projects(name, root_path, created_at) VALUES (?, ?, ?)",
        (name, root_path, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def init_project(conn: sqlite3.Connection, name: str, root_path: str) -> dict:
    project_id = ensure_project(conn, name, root_path)
    return {"status": "ok", "project": {"id": project_id, "name": name, "root_path": root_path}}


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


def remember(
    conn: sqlite3.Connection,
    text: str,
    project: str = "default",
    memory_type: str = "fact",
    pramana: str = "smriti",
    confidence: float = 0.75,
    priority: int = 5,
    metadata: dict | None = None,
) -> dict:
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
    project_id = ensure_project(conn, project)
    timestamp = now_iso()
    cur = conn.execute(
        """
        INSERT INTO memories(project_id, type, pramana, text, confidence, priority, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, memory_type, pramana, text, float(confidence), int(priority), json.dumps(metadata or {}), timestamp, timestamp),
    )
    memory_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO memory_fts(memory_id, project_id, text, type, pramana) VALUES (?, ?, ?, ?, ?)",
        (memory_id, project_id, text, memory_type, pramana),
    )
    memory_entity = ensure_entity(conn, project_id, "memory", f"memory:{memory_id}")
    for term in extract_terms(text):
        term_entity = ensure_entity(conn, project_id, "concept", term)
        add_edge(conn, project_id, memory_entity, "mentions", term_entity, memory_id=memory_id, confidence=0.7)
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
        },
    }


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


def _read_thread_text(path: Path) -> str:
    if path.stat().st_size > MAX_THREAD_BYTES:
        raise ValueError(f"thread exceeds the {MAX_THREAD_BYTES // (1024 * 1024)} MB ingestion limit")
    if path.suffix.lower() == ".jsonl":
        parts = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                parts.append(line.strip())
            else:
                parts.extend(_collect_json_strings(payload))
        return "\n\n".join(part.strip() for part in parts if part and part.strip())
    return path.read_text(encoding="utf-8", errors="ignore")


def _candidate_memory_type(text: str) -> str | None:
    lowered = text.lower()
    if "verification evidence" in lowered or "pytest passed" in lowered or "test passed" in lowered:
        return "evidence"
    if lowered.startswith("decision:") or "we decided" in lowered:
        return "decision"
    if " must " in f" {lowered} " or " should " in f" {lowered} ":
        return "constraint"
    return None


def ingest_thread(conn: sqlite3.Connection, path: Path, project: str = "default", title: str | None = None) -> dict:
    init_schema(conn)
    path = path.resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"thread path does not exist or is not a file: {path}")
    text = _read_thread_text(path)
    project_id = ensure_project(conn, project)
    source_title = title or path.name
    source_id = upsert_source(
        conn,
        project_id,
        "thread",
        str(path),
        source_title,
        sha256_text(text),
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


def _repo_stat_manifest(root: Path) -> tuple[str, list[tuple[Path, object]], list[dict[str, str]]]:
    rejected: list[dict[str, str]] = []
    path_stats = [(path, path.stat()) for path in walk_repo(root, rejected=rejected)]
    manifest_lines = [
        f"{path.relative_to(root).as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}"
        for path, stat in path_stats
    ]
    manifest_lines.extend(f"!{item['path']}\0{item['reason']}" for item in rejected)
    return sha256_text("\n".join(manifest_lines)), path_stats, rejected


def ingest_repo(conn: sqlite3.Connection, root: Path, project: str = "default", force: bool = False) -> dict:
    init_schema(conn)
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repo path does not exist or is not a directory: {root}")
    project_id = ensure_project(conn, project, str(root))
    manifest_digest, path_stats, rejected = _repo_stat_manifest(root)
    prior_manifest = conn.execute("SELECT digest, file_count FROM repo_manifests WHERE project_id = ?", (project_id,)).fetchone()
    if not force and prior_manifest and prior_manifest["digest"] == manifest_digest and int(prior_manifest["file_count"]) == len(path_stats):
        return {
            "status": "ok", "project": project, "root": str(root), "indexed_files": len(path_stats),
            "updated_files": 0, "unchanged_files": len(path_stats), "removed_files": 0,
            "skipped_files": len(rejected), "symbols": 0, "edges": 0, "chunks": 0, "manifest_unchanged": True,
        }
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
    for path, stat in path_stats:
        path_key = str(path)
        seen_paths.add(path_key)
        row = existing.get(path_key)
        prior_metadata = {}
        if row:
            try:
                prior_metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                prior_metadata = {}
            if prior_metadata.get("mtime_ns") == stat.st_mtime_ns and prior_metadata.get("size") == stat.st_size:
                indexed_files += 1
                unchanged_files += 1
                continue
            if "mtime_ns" not in prior_metadata:
                try:
                    indexed_at = datetime.fromisoformat(row["updated_at"]).timestamp()
                except (TypeError, ValueError):
                    indexed_at = 0
                if stat.st_mtime <= indexed_at:
                    indexed_files += 1
                    unchanged_files += 1
                    continue
            text = read_text(path)
            if text is not None and sha256_text(text) == row["hash"]:
                if "mtime_ns" in prior_metadata:
                    metadata = {**prior_metadata, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
                    conn.execute("UPDATE sources SET metadata_json = ?, updated_at = ? WHERE id = ?", (json.dumps(metadata), now_iso(), int(row["id"])))
                indexed_files += 1
                unchanged_files += 1
                continue
        record = build_file_record(root, path)
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
            {"relative_path": record.relative_path, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size},
        )
        file_entity = ensure_entity(conn, project_id, "file", record.relative_path)
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
        indexed_files += 1
        updated_files += 1
    for path_key, row in existing.items():
        if path_key in seen_paths:
            continue
        source_id = int(row["id"])
        conn.execute("DELETE FROM chunk_fts WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM edges WHERE project_id = ? AND source_id = ?", (project_id, source_id))
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        removed_files += 1
    if updated_files or removed_files:
        conn.execute(
            "DELETE FROM entities WHERE project_id = ? AND type IN ('file', 'symbol', 'import') "
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
        "skipped_files": skipped_files, "symbols": symbols, "edges": edges, "chunks": chunks, "manifest_unchanged": False,
    }


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


def search(conn: sqlite3.Connection, query: str, project: str | None = None, limit: int = 8) -> dict:
    init_schema(conn)
    query = str(query)[:10_000]
    limit = max(1, min(MAX_SEARCH_LIMIT, int(limit)))
    fts_query = query_to_fts(query)
    project_id = None
    if project:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
        if not row:
            return {"status": "ok", "query": query, "memories": [], "chunks": []}
        project_id = int(row["id"])
    project_count = int(conn.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"])
    candidate_limit = limit if project_count <= 1 else min(5000, max(512, limit * 64))

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
                       m.priority, m.status, m.metadata_json
                FROM memories m
                JOIN projects p ON p.id = m.project_id
                WHERE m.id IN ({placeholders}) AND m.status IN ('active', 'pinned')
                """,
                memory_ids,
            )
        }
        for candidate in selected_memories:
            item = rows_by_id.get(int(candidate["memory_id"]))
            if item:
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
    selected_chunks = [
        row for row in chunk_candidates
        if project_id is None or int(row["project_id"]) == project_id
    ][:limit]
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
                chunks.append(item)
    selected = {"memories": [item["id"] for item in memories], "chunks": [item["id"] for item in chunks]}
    conn.execute(
        "INSERT INTO recall_logs(project_id, query, selected_json, created_at) VALUES (?, ?, ?, ?)",
        (project_id, query, json.dumps(selected), now_iso()),
    )
    conn.commit()
    return {"status": "ok", "query": query, "memories": memories, "chunks": chunks}


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


def stale_check(conn: sqlite3.Connection, project: str = "default", deep: bool = False) -> dict:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not row:
        return {"status": "ok", "project": project, "mode": "sha256" if deep else "stat-manifest", "state": "unknown", "fresh": 0, "changed": 0, "missing": 0, "added": 0, "details": []}
    details = []
    counts = {"fresh": 0, "changed": 0, "missing": 0, "added": 0, "uninspectable": 0}
    indexed_titles = set()
    project_row = conn.execute("SELECT root_path FROM projects WHERE id = ?", (int(row["id"]),)).fetchone()
    root_path = Path(project_row["root_path"]).resolve() if project_row and project_row["root_path"] else None
    current_by_path = {}
    rejected: list[dict[str, str]] = []
    manifest_digest = None
    if root_path and root_path.exists():
        manifest_digest, path_stats, rejected = _repo_stat_manifest(root_path)
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
                return {
                    "status": "ok", "project": project, "mode": "stat-manifest",
                    "state": "stale" if rejected else "fresh",
                    "fresh": len(path_stats), "changed": 0, "missing": 0, "added": 0,
                    "uninspectable": len(rejected), "details": rejected_details,
                }
    for source in conn.execute("SELECT id, path, title, hash, metadata_json, updated_at FROM sources WHERE project_id = ? AND kind = 'file'", (int(row["id"]),)):
        path = Path(source["path"])
        indexed_titles.add(str(source["title"]).replace("\\", "/"))
        stat = current_by_path.get(str(path))
        if stat is None:
            status = "missing"
        elif deep:
            try:
                current_hash = sha256_text(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                current_hash = ""
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
    return {"status": "ok", "project": project, "mode": "sha256" if deep else "stat-manifest", "state": state, **counts, "details": details}


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
