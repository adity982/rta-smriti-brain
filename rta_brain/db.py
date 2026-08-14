import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .ingest import build_file_record, chunk_text, extract_terms, sha256_text, walk_repo


VALID_PRAMANA = {"pratyaksha", "sabda", "anumana", "smriti", "kalpana"}


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
        """
    )
    conn.commit()


def ensure_project(conn: sqlite3.Connection, name: str, root_path: str | None = None) -> int:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        if root_path:
            conn.execute("UPDATE projects SET root_path = COALESCE(root_path, ?) WHERE id = ?", (root_path, row["id"]))
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
    if pramana not in VALID_PRAMANA:
        raise ValueError(f"invalid pramana '{pramana}', expected one of {sorted(VALID_PRAMANA)}")
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


def _candidate_memory_type(text: str) -> tuple[str, str] | None:
    lowered = text.lower()
    if "verification evidence" in lowered or "pytest passed" in lowered or "test passed" in lowered:
        return ("evidence", "pratyaksha")
    if lowered.startswith("decision:") or "we decided" in lowered:
        return ("decision", "sabda")
    if " must " in f" {lowered} " or " should " in f" {lowered} ":
        return ("constraint", "sabda")
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
    for paragraph in re.split(r"\n\s*\n|(?<=\.)\s+", text):
        candidate = paragraph.strip()
        if len(candidate) < 24:
            continue
        classification = _candidate_memory_type(candidate)
        if not classification:
            continue
        memory_type, pramana = classification
        remember(
            conn,
            candidate[:1000],
            project=project,
            memory_type=memory_type,
            pramana=pramana,
            confidence=0.82,
            priority=7 if memory_type != "evidence" else 6,
            metadata={"source": "ingest-thread", "source_path": str(path), "source_title": source_title},
        )
        promoted += 1
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


def ingest_repo(conn: sqlite3.Connection, root: Path, project: str = "default") -> dict:
    init_schema(conn)
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"repo path does not exist or is not a directory: {root}")
    project_id = ensure_project(conn, project, str(root))
    indexed_files = 0
    symbols = 0
    edges = 0
    chunks = 0
    for path in walk_repo(root):
        record = build_file_record(root, path)
        if record is None:
            continue
        source_id = upsert_source(
            conn,
            project_id,
            "file",
            str(record.path),
            record.relative_path,
            record.sha256,
            {"relative_path": record.relative_path},
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
    conn.commit()
    return {"status": "ok", "project": project, "root": str(root), "indexed_files": indexed_files, "symbols": symbols, "edges": edges, "chunks": chunks}


def query_to_fts(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    if not tokens:
        return '""'
    return " OR ".join(tokens[:12])


def search(conn: sqlite3.Connection, query: str, project: str | None = None, limit: int = 8) -> dict:
    init_schema(conn)
    project_filter = ""
    params: list = [query_to_fts(query)]
    if project:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
        if not row:
            return {"status": "ok", "query": query, "memories": [], "chunks": []}
        project_filter = " AND m.project_id = ?"
        params.append(int(row["id"]))
    params.append(limit)
    memories = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT m.id, p.name AS project, m.type, m.pramana, m.text, m.confidence, m.priority, m.status,
                   bm25(memory_fts) AS rank
            FROM memory_fts
            JOIN memories m ON m.id = memory_fts.memory_id
            JOIN projects p ON p.id = m.project_id
            WHERE memory_fts MATCH ? {project_filter}
              AND m.status IN ('active', 'pinned')
            ORDER BY rank ASC, m.priority DESC
            LIMIT ?
            """,
            params,
        )
    ]
    chunk_params: list = [query_to_fts(query)]
    chunk_filter = ""
    if project:
        chunk_filter = " AND cft.project_id = ?"
        chunk_params.append(params[1])
    chunk_params.append(limit)
    chunks = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT c.id, p.name AS project, cft.path, substr(c.text, 1, 500) AS text,
                   s.hash AS source_hash, bm25(chunk_fts) AS rank
            FROM chunk_fts cft
            JOIN chunks c ON c.id = cft.chunk_id
            JOIN sources s ON s.id = c.source_id
            JOIN projects p ON p.id = cft.project_id
            WHERE chunk_fts MATCH ? {chunk_filter}
            ORDER BY rank ASC
            LIMIT ?
            """,
            chunk_params,
        )
    ]
    selected = {"memories": [item["id"] for item in memories], "chunks": [item["id"] for item in chunks]}
    project_id = params[1] if project and len(params) > 2 else None
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
    init_schema(conn)
    project_id = ensure_project(conn, project)
    nodes = [dict(row) for row in conn.execute("SELECT id, type, name, canonical_key FROM entities WHERE project_id = ? ORDER BY type, name LIMIT ?", (project_id, limit))]
    edges = [
        dict(row)
        for row in conn.execute(
            """
            SELECT e.id, f.name AS from_name, e.relation, t.name AS to_name, e.confidence
            FROM edges e
            JOIN entities f ON f.id = e.from_entity_id
            JOIN entities t ON t.id = e.to_entity_id
            WHERE e.project_id = ?
            ORDER BY e.id
            LIMIT ?
            """,
            (project_id, limit),
        )
    ]
    return {"status": "ok", "project": project, "nodes": nodes, "edges": edges, "counts": {"nodes": len(nodes), "edges": len(edges)}}


def stale_check(conn: sqlite3.Connection, project: str = "default") -> dict:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not row:
        return {"status": "ok", "project": project, "fresh": 0, "changed": 0, "missing": 0, "details": []}
    details = []
    counts = {"fresh": 0, "changed": 0, "missing": 0}
    for source in conn.execute("SELECT id, path, title, hash FROM sources WHERE project_id = ? AND kind = 'file'", (int(row["id"]),)):
        path = Path(source["path"])
        if not path.exists():
            status = "missing"
        else:
            try:
                current_hash = sha256_text(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                current_hash = ""
            status = "fresh" if current_hash == source["hash"] else "changed"
        counts[status] += 1
        details.append({"source_id": source["id"], "path": source["path"], "title": source["title"], "status": status})
    return {"status": "ok", "project": project, **counts, "details": details}


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
