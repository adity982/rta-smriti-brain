"""Deterministic, provenance-aware pre-action governance."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from .db import VALID_PRAMANA, init_schema, now_iso, validate_provenance
from .ingest import read_text, sha256_text


POLICY_KINDS = frozenset({
    "constraint", "failed_approach", "fragile_path", "required_check", "prohibited_repetition",
})
POLICY_EFFECTS = frozenset({"warn", "block"})
BLOCKING_PRAMANA = frozenset({"pratyaksha", "sabda"})


def _project_id(conn, project: str) -> int:
    init_schema(conn)
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project,)).fetchone()
    if not row:
        raise ValueError(f"project does not exist: {project}")
    return int(row["id"])


def _bounded_text(value, name: str, *, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum:,} characters")
    return text


def _normalized_expiry(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _normalized_path_glob(value: str) -> str:
    pattern = _bounded_text(value, "path_glob", maximum=1_000).replace("\\", "/").strip("/")
    if pattern and (Path(pattern).is_absolute() or ".." in pattern.split("/")):
        raise ValueError("path_glob must stay relative to the canonical project root")
    return pattern


def _normalized_action_path(value: str | None) -> str | None:
    text = _bounded_text(value, "path", maximum=4_000).replace("\\", "/").strip()
    if not text:
        return None
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        raise ValueError("path must be project-relative")
    parts = [part for part in text.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        raise ValueError("path must be project-relative")
    return "/".join(parts)


def _policy_dict(row) -> dict:
    policy = dict(row)
    policy["overrideable"] = bool(policy["overrideable"])
    try:
        policy["provenance"] = json.loads(policy.pop("provenance_json") or "{}")
    except json.JSONDecodeError:
        policy["provenance"] = {}
    return policy


def validate_policy_input(
    *,
    kind: str,
    statement: str,
    effect: str = "warn",
    action_contains: str = "",
    path_glob: str = "",
    required_check: str = "",
    pramana: str = "smriti",
    confidence: float = 0.75,
    provenance: dict | None = None,
    overrideable: bool = True,
    expires_at: str | None = None,
) -> dict:
    """Validate and normalize portable policy fields without mutating a brain."""
    selected_kind = str(kind).strip().lower()
    selected_effect = str(effect).strip().lower()
    selected_pramana = str(pramana).strip().lower()
    if selected_kind not in POLICY_KINDS:
        raise ValueError(f"unknown governance policy kind: {selected_kind}")
    if selected_effect not in POLICY_EFFECTS:
        raise ValueError("governance effect must be warn or block")
    if selected_pramana not in VALID_PRAMANA:
        raise ValueError(f"unknown pramana: {selected_pramana}")
    selected_confidence = float(confidence)
    if not 0 <= selected_confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return {
        "kind": selected_kind,
        "statement": _bounded_text(statement, "statement", maximum=8_000, required=True),
        "effect": selected_effect,
        "action_contains": _bounded_text(action_contains, "action_contains", maximum=1_000).casefold(),
        "path_glob": _normalized_path_glob(path_glob),
        "required_check": _bounded_text(required_check, "required_check", maximum=500).casefold(),
        "pramana": selected_pramana,
        "confidence": selected_confidence,
        "provenance": validate_provenance(provenance),
        "overrideable": bool(overrideable),
        "expires_at": _normalized_expiry(expires_at),
    }


def create_policy(
    conn,
    *,
    project: str,
    kind: str,
    statement: str,
    effect: str = "warn",
    action_contains: str = "",
    path_glob: str = "",
    required_check: str = "",
    pramana: str = "smriti",
    confidence: float = 0.75,
    provenance: dict | None = None,
    overrideable: bool = True,
    expires_at: str | None = None,
) -> dict:
    validated = validate_policy_input(
        kind=kind, statement=statement, effect=effect, action_contains=action_contains,
        path_glob=path_glob, required_check=required_check, pramana=pramana,
        confidence=confidence, provenance=provenance, overrideable=overrideable,
        expires_at=expires_at,
    )
    project_id = _project_id(conn, project)
    normalized_provenance = validated["provenance"]
    if normalized_provenance["verification_status"] == "verified" and not normalized_provenance["source_hash"]:
        project_row = conn.execute("SELECT root_path FROM projects WHERE id = ?", (project_id,)).fetchone()
        root = Path(project_row["root_path"]).resolve() if project_row and project_row["root_path"] else None
        source = Path(str(normalized_provenance["source_path"] or ""))
        if root and normalized_provenance["source_path"]:
            try:
                resolved = (root / source).resolve(strict=True) if not source.is_absolute() else source.resolve(strict=True)
                resolved.relative_to(root)
                source_text = read_text(resolved, max_bytes=16_000_000)
                if source_text is not None:
                    normalized_provenance["source_hash"] = sha256_text(source_text)
                    normalized_provenance["source_path"] = resolved.relative_to(root).as_posix()
            except (OSError, ValueError):
                pass
    created_at = now_iso()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO governance_policies(
                project_id, kind, statement, effect, action_contains, path_glob,
                required_check, pramana, confidence, provenance_json, overrideable,
                expires_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                project_id,
                validated["kind"],
                validated["statement"],
                validated["effect"],
                validated["action_contains"],
                validated["path_glob"],
                validated["required_check"],
                validated["pramana"],
                validated["confidence"],
                json.dumps(normalized_provenance, sort_keys=True),
                int(validated["overrideable"]),
                validated["expires_at"],
                created_at,
            ),
        )
        policy_id = int(cursor.lastrowid)
    row = conn.execute("SELECT * FROM governance_policies WHERE id = ?", (policy_id,)).fetchone()
    return {"status": "ok", "project": project, "policy": _policy_dict(row)}


def list_policies(conn, *, project: str, include_retired: bool = False) -> dict:
    project_id = _project_id(conn, project)
    rows = conn.execute(
        """
        SELECT * FROM governance_policies
        WHERE project_id = ? AND (? OR status = 'active')
        ORDER BY status = 'active' DESC, id
        """,
        (project_id, int(bool(include_retired))),
    ).fetchall()
    return {"status": "ok", "project": project, "policies": [_policy_dict(row) for row in rows]}


def retire_policy(conn, *, project: str, policy_id: int, reason: str) -> dict:
    project_id = _project_id(conn, project)
    retired_reason = _bounded_text(reason, "retirement reason", maximum=2_000, required=True)
    with conn:
        cursor = conn.execute(
            """
            UPDATE governance_policies
            SET status = 'retired', retired_reason = ?, retired_at = ?
            WHERE id = ? AND project_id = ? AND status = 'active'
            """,
            (retired_reason, now_iso(), int(policy_id), project_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"active governance policy does not exist: {policy_id}")
    row = conn.execute("SELECT * FROM governance_policies WHERE id = ?", (int(policy_id),)).fetchone()
    return {"status": "ok", "project": project, "policy": _policy_dict(row)}


def _is_expired(policy: dict) -> bool:
    if not policy.get("expires_at"):
        return False
    expires = datetime.fromisoformat(str(policy["expires_at"]).replace("Z", "+00:00"))
    return expires.astimezone(timezone.utc) <= datetime.now(timezone.utc)


def _scope_matches(policy: dict, action: str, path: str | None) -> bool:
    action_pattern = str(policy.get("action_contains") or "")
    if action_pattern and action_pattern not in action.casefold():
        return False
    path_pattern = str(policy.get("path_glob") or "")
    if path_pattern:
        if not path:
            return False
        normalized_path = str(path).casefold()
        if not PurePosixPath(normalized_path).match(path_pattern.casefold()):
            return False
    return True


def _blocking_trust(policy: dict) -> bool:
    provenance = policy.get("provenance") or {}
    return (
        policy.get("pramana") in BLOCKING_PRAMANA
        and float(policy.get("confidence") or 0) >= 0.8
        and provenance.get("verification_status") == "verified"
        and bool(provenance.get("source_hash"))
    )


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_dict(row) -> dict:
    receipt = dict(row)
    receipt["matched_policy_ids"] = json.loads(receipt.pop("matched_policy_ids_json"))
    receipt["evidence"] = json.loads(receipt.pop("evidence_json"))
    return receipt


def preflight(
    conn,
    *,
    project: str,
    action: str,
    path: str | None = None,
    completed_checks: list[str] | None = None,
    override_reason: str | None = None,
    actor: str = "operator",
) -> dict:
    action_text = _bounded_text(action, "action", maximum=8_000, required=True)
    path_text = _normalized_action_path(path)
    if completed_checks is not None and not isinstance(completed_checks, list):
        raise ValueError("completed_checks must be a list")
    if len(completed_checks or []) > 100:
        raise ValueError("completed_checks exceeds 100 entries")
    check_evidence = []
    for check in completed_checks or []:
        if isinstance(check, str):
            check_evidence.append({
                "name": _bounded_text(check, "completed check", maximum=500, required=True).casefold(),
                "verification_status": "owner_attested",
            })
        elif isinstance(check, dict):
            name = _bounded_text(check.get("name"), "completed check name", maximum=500, required=True).casefold()
            provenance = validate_provenance(check.get("provenance"))
            check_evidence.append({"name": name, "verification_status": provenance["verification_status"], "provenance": provenance})
        else:
            raise ValueError("each completed check must be a name or evidence object")
    checks = {item["name"] for item in check_evidence}
    policies = list_policies(conn, project=project)["policies"]
    matches = []
    satisfied = []
    for policy in policies:
        if _is_expired(policy) or not _scope_matches(policy, action_text, path_text):
            continue
        required_check = str(policy.get("required_check") or "")
        if required_check and required_check in checks:
            satisfied.append(int(policy["id"]))
            continue
        requested_effect = str(policy["effect"])
        trusted_to_block = _blocking_trust(policy)
        effective_effect = requested_effect if requested_effect != "block" or trusted_to_block else "warn"
        reason = policy["statement"]
        if requested_effect == "block" and not trusted_to_block:
            reason += " (demoted to warning: insufficient trust for an independent block)"
        matches.append({
            "policy_id": int(policy["id"]),
            "kind": policy["kind"],
            "statement": policy["statement"],
            "requested_effect": requested_effect,
            "effective_effect": effective_effect,
            "reason": reason,
            "required_check": required_check or None,
            "overrideable": bool(policy["overrideable"]),
            "pramana": policy["pramana"],
            "confidence": float(policy["confidence"]),
            "provenance": policy["provenance"],
        })
    initial_decision = "block" if any(item["effective_effect"] == "block" for item in matches) else (
        "warn" if matches else "allow"
    )
    final_decision = initial_decision
    receipt = None
    if override_reason:
        reason = _bounded_text(override_reason, "override_reason", maximum=4_000, required=True)
        actor_text = _bounded_text(actor, "actor", maximum=300, required=True)
        hard_block = any(
            item["effective_effect"] == "block" and not item["overrideable"] for item in matches
        )
        final_decision = "block" if hard_block else (
            "allow_with_override" if initial_decision in {"block", "warn"} else "allow"
        )
        project_id = _project_id(conn, project)
        evidence = {"matches": matches, "completed_checks": check_evidence, "satisfied_policy_ids": sorted(satisfied)}
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO governance_receipts(
                    project_id, action, path, actor, initial_decision, final_decision,
                    override_reason, matched_policy_ids_json, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, action_text, path_text, actor_text, initial_decision,
                    final_decision, reason,
                    json.dumps([item["policy_id"] for item in matches]),
                    json.dumps(evidence, sort_keys=True), now_iso(),
                ),
            )
            receipt_id = int(cursor.lastrowid)
        row = conn.execute("SELECT * FROM governance_receipts WHERE id = ?", (receipt_id,)).fetchone()
        receipt = _receipt_dict(row)
    policy_digest = _digest([
        {key: value for key, value in policy.items() if key not in {"created_at", "retired_at"}}
        for policy in policies if not _is_expired(policy)
    ])
    action_digest = _digest({"action": action_text, "path": path_text, "completed_checks": check_evidence})
    created_at = now_iso()
    valid_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(microsecond=0).isoformat()
    project_id = _project_id(conn, project)
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO governance_decisions(project_id, action_digest, policy_digest, decision, valid_until, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, action_digest, policy_digest, final_decision, valid_until, created_at),
        )
        conn.execute(
            "DELETE FROM governance_decisions WHERE project_id = ? AND id NOT IN (SELECT id FROM governance_decisions WHERE project_id = ? ORDER BY id DESC LIMIT 1000)",
            (project_id, project_id),
        )
    decision_receipt = {
        "id": int(cursor.lastrowid), "action_digest": action_digest, "policy_digest": policy_digest,
        "decision": final_decision, "created_at": created_at, "valid_until": valid_until,
    }
    return {
        "status": "ok",
        "project": project,
        "action": action_text,
        "path": path_text,
        "initial_decision": initial_decision,
        "decision": final_decision,
        "matches": matches,
        "completed_checks": sorted(checks),
        "completed_check_evidence": check_evidence,
        "satisfied_policy_ids": sorted(satisfied),
        "override_receipt": receipt,
        "decision_receipt": decision_receipt,
    }


def list_receipts(conn, *, project: str, limit: int = 100) -> dict:
    project_id = _project_id(conn, project)
    bounded_limit = max(1, min(int(limit), 500))
    rows = conn.execute(
        """
        SELECT * FROM governance_receipts
        WHERE project_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (project_id, bounded_limit),
    ).fetchall()
    return {"status": "ok", "project": project, "receipts": [_receipt_dict(row) for row in rows]}
