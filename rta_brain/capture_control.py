"""Bounded operator and agent control views for universal capture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .capture import (
    list_capture_policies,
    list_capture_sources,
    read_capture_replay,
    verify_capture_project_binding,
    verify_journal,
)
from .capture_daemon import capture_status
from .capture_spool import SpoolUnsafeError, read_capture_spool_usage, source_token

DIAGNOSTIC_JOURNAL_EVENT_LIMIT = 1_000


def public_capture_daemon_status(database: Path) -> dict[str, Any]:
    payload = dict(capture_status(database))
    return {
        key: payload[key]
        for key in (
            "status", "state", "process_alive", "process_identity_matches",
        )
        if key in payload
    }


def capture_status_report(
    conn,
    *,
    database: Path,
    project: str,
) -> dict[str, Any]:
    """Return content-free bounded lifecycle status."""

    sources = list_capture_sources(conn, project=project)["sources"]
    policies = list_capture_policies(conn, project=project)["policies"]
    warnings = []
    try:
        project_source_tokens = {
            source_token(str(source["source_id"]), project=project)
            for source in sources
        }
        spool = read_capture_spool_usage(
            database,
            source_tokens=project_source_tokens,
        )
        queue = {
            "state": "verified",
            "records": int(spool["total_records"]),
            "bytes": int(spool["total_bytes"]),
            "sources": int(spool["source_count"]),
        }
    except SpoolUnsafeError:
        queue = {
            "state": "unavailable",
            "records": None,
            "bytes": None,
            "sources": None,
        }
        warnings.append({
            "code": "capture_spool_usage_unavailable",
            "message": "Queue occupancy could not be verified. Capture remains fail-closed.",
        })
    return {
        "status": "degraded" if warnings else "ok",
        "daemon": public_capture_daemon_status(database),
        "sources": sources,
        "policies": policies,
        "queue": queue,
        "warnings": warnings,
    }


def capture_replay(
    conn,
    *,
    project: str,
    active_root: Path,
    mode: str = "chronological",
    after_sequence: int = 0,
    limit: int = 100,
    privacy_ceiling: str = "internal",
) -> dict[str, Any]:
    """Build a read-only deterministic chronological or causal replay page."""

    verify_capture_project_binding(
        conn,
        project=project,
        active_root=active_root,
    )
    return read_capture_replay(
        conn, project=project, mode=mode, after_sequence=after_sequence,
        limit=limit, privacy_ceiling=privacy_ceiling,
    )


def capture_diagnostics(
    conn,
    *,
    database: Path,
    project: str,
    active_root: Path,
) -> dict[str, Any]:
    """Return bounded integrity and lifecycle diagnostics without local paths."""

    verify_capture_project_binding(
        conn,
        project=project,
        active_root=active_root,
    )
    status = capture_status_report(conn, database=database, project=project)
    journal = verify_journal(
        conn,
        project=project,
        max_events=DIAGNOSTIC_JOURNAL_EVENT_LIMIT,
    )
    events = conn.execute(
        """
        SELECT COUNT(*) AS events,
               COALESCE(SUM(redaction_count), 0) AS redactions,
               COALESCE(SUM(truncation_count), 0) AS truncations,
               COALESCE(SUM(CASE WHEN gap_state = 'detected' THEN 1 ELSE 0 END), 0) AS gaps
        FROM capture_events e JOIN projects p ON p.id = e.project_id
        WHERE p.name = ?
        """,
        (project,),
    ).fetchone()
    return {
        **status,
        "journal": journal,
        "events": {
            "count": int(events["events"]),
            "redactions": int(events["redactions"]),
            "truncations": int(events["truncations"]),
            "gaps": int(events["gaps"]),
        },
        "canonical_root_verified": True,
    }
