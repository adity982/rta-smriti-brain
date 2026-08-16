"""Bounded, privacy-safe diagnostics for retrieval behavior."""

from __future__ import annotations

from time import perf_counter

from .db import get_project_settings, indexed_freshness, init_schema, search


def retrieval_diagnostics(conn, query: str, *, project: str = "default", limit: int = 8) -> dict:
    init_schema(conn)
    bounded_limit = max(1, min(50, int(limit)))
    started = perf_counter()
    result = search(conn, query, project=project, limit=bounded_limit)
    latency_ms = round((perf_counter() - started) * 1000, 3)
    project_row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    project_id = int(project_row["id"]) if project_row else None
    source_count = chunk_count = embedding_count = 0
    parser_counts: dict[str, int] = {}
    warning_count = 0
    if project_id is not None:
        source_count = int(conn.execute(
            "SELECT COUNT(*) AS c FROM sources WHERE project_id = ? AND kind = 'file'", (project_id,),
        ).fetchone()["c"])
        chunk_count = int(conn.execute(
            "SELECT COUNT(*) AS c FROM chunks c JOIN sources s ON s.id = c.source_id WHERE s.project_id = ? AND s.kind = 'file'",
            (project_id,),
        ).fetchone()["c"])
        embedding_count = int(conn.execute(
            "SELECT COUNT(*) AS c FROM chunk_embeddings WHERE project_id = ?", (project_id,),
        ).fetchone()["c"])
        for row in conn.execute(
            "SELECT metadata_json FROM sources WHERE project_id = ? AND kind = 'file'", (project_id,),
        ):
            import json
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except ValueError:
                metadata = {}
            parser = str(metadata.get("parser") or "unknown")
            parser_counts[parser] = parser_counts.get(parser, 0) + 1
            warning_count += len(metadata.get("parser_warnings") or [])
    settings = get_project_settings(conn, project) if project_row else {}
    diagnostics = []
    for index, item in enumerate(result.get("chunks", []), start=1):
        diagnostics.append({
            "path": item.get("path"),
            "text": item.get("text", ""),
            "ranking": {
                "position": index,
                "bm25_rank": item.get("rank"),
                "lexical_score": item.get("lexical_score", 1.0 / index),
                "semantic_score": item.get("semantic_score", 0.0),
                "hybrid_score": item.get("hybrid_score", 1.0 / index),
            },
            "evidence": {
                "source_hash": item.get("source_hash"),
                "verification_status": "indexed_snapshot",
            },
        })
    return {
        "status": "ok",
        "project": project,
        "query": str(query),
        "latency_ms": latency_ms,
        "retrieval": result.get("retrieval", {}),
        "index": {
            "sources": source_count,
            "chunks": chunk_count,
            "embeddings": embedding_count,
            "embedding_coverage": round(embedding_count / chunk_count, 6) if chunk_count else 0.0,
            "configured_parser": settings.get("parser_adapter"),
            "parsers_used": parser_counts,
            "parser_warnings": warning_count,
        },
        "freshness": indexed_freshness(conn, project),
        "results": diagnostics,
    }
