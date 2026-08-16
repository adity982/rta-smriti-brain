"""Evidence-aware reinforcement and conservative memory decay."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import init_schema, now_iso


def apply_memory_feedback(conn, *, project: str, memory_id: int, outcome: str, evidence: str = "") -> dict:
    init_schema(conn)
    selected = str(outcome).strip().lower()
    if selected not in {"helpful", "neutral", "harmful"}:
        raise ValueError("memory outcome must be helpful, neutral, or harmful")
    evidence_text = str(evidence or "").strip()
    if len(evidence_text) > 4_000:
        raise ValueError("memory feedback evidence exceeds 4,000 characters")
    row = conn.execute(
        """
        SELECT m.*, p.name AS project FROM memories m JOIN projects p ON p.id = m.project_id
        WHERE m.id = ? AND p.name = ?
        """,
        (int(memory_id), project),
    ).fetchone()
    if not row:
        raise ValueError(f"memory does not exist in project '{project}': {memory_id}")
    confidence_delta = {"helpful": 0.05, "neutral": 0.0, "harmful": -0.1}[selected]
    priority_delta = {"helpful": 1, "neutral": 0, "harmful": -1}[selected]
    confidence = max(0.05, min(1.0, float(row["confidence"]) + confidence_delta))
    priority = max(1, min(10, int(row["priority"]) + priority_delta))
    with conn:
        conn.execute(
            "INSERT INTO memory_feedback(project_id, memory_id, outcome, evidence, created_at) VALUES (?, ?, ?, ?, ?)",
            (int(row["project_id"]), int(memory_id), selected, evidence_text, now_iso()),
        )
        conn.execute(
            "UPDATE memories SET confidence = ?, priority = ?, updated_at = ? WHERE id = ?",
            (confidence, priority, now_iso(), int(memory_id)),
        )
    updated = conn.execute(
        "SELECT id, type, pramana, text, confidence, priority, status, updated_at FROM memories WHERE id = ?",
        (int(memory_id),),
    ).fetchone()
    return {"status": "ok", "project": project, "outcome": selected, "memory": dict(updated)}


def run_conservative_decay(conn, *, project: str, minimum_age_days: int = 90, step: float = 0.03) -> dict:
    init_schema(conn)
    days = max(0, min(3650, int(minimum_age_days)))
    bounded_step = max(0.001, min(0.1, float(step)))
    project_row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not project_row:
        raise ValueError(f"project does not exist: {project}")
    project_id = int(project_row["id"])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT m.id, m.pramana, m.confidence, m.priority, m.status, m.updated_at,
               mp.verification_status,
               EXISTS(SELECT 1 FROM memory_feedback mf WHERE mf.memory_id = m.id AND mf.outcome = 'helpful') AS reinforced
        FROM memories m LEFT JOIN memory_provenance mp ON mp.memory_id = m.id
        WHERE m.project_id = ? AND m.status = 'active'
        ORDER BY m.id
        """,
        (project_id,),
    ).fetchall()
    decayed = protected = 0
    with conn:
        for row in rows:
            if row["verification_status"] == "verified" or row["pramana"] in {"pratyaksha", "sabda"}:
                protected += 1
                continue
            if row["reinforced"] or str(row["updated_at"]) > cutoff or row["pramana"] not in {"kalpana", "anumana"}:
                continue
            confidence = max(0.1, round(float(row["confidence"]) - bounded_step, 6))
            priority = max(1, int(row["priority"]) - (1 if confidence <= 0.35 else 0))
            status = "superseded" if confidence <= 0.15 else "active"
            conn.execute(
                "UPDATE memories SET confidence = ?, priority = ?, status = ?, updated_at = ? WHERE id = ?",
                (confidence, priority, status, now_iso(), int(row["id"])),
            )
            decayed += 1
    return {"status": "ok", "project": project, "decayed": decayed, "protected_verified": protected}
