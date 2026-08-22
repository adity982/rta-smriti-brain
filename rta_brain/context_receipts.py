"""Immutable metadata receipts for deterministic context compilation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any

from . import db

RECEIPT_SCHEMA_VERSION = "rta-smriti.context-compilation-receipt/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PRIVACY_ORDER = {"public": 0, "internal": 1, "sensitive": 2, "restricted": 3}
_TERMINAL_STATUSES = {"complete", "abstained", "failed"}
_TASK_STATUSES = {"success", "partial_success", "failure", "interruption"}
_ATTRIBUTION_LEVELS = {"observed": 0, "correlated": 1, "operator_confirmed": 2}
_ASSESSMENTS = {"helpful", "harmful", "neutral", "unused", "unknown"}
_ACTOR_TYPES = {"operator", "agent", "system"}


class CompilationStateChanged(RuntimeError):
    """Signal a failed final fence check without persisting a receipt."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("compilation state changed before receipt commit")
        self.result = json.loads(_canonical(result))


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return json.loads(_canonical(value))


def _required_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _receipt_rows(selection: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for receipt in selection.get("receipts", []):
        if not isinstance(receipt, dict):
            raise TypeError("selection receipt must be an object")
        disposition = str(receipt.get("disposition") or "").strip()
        stage = str(receipt.get("stage") or "").strip()
        if stage == "pre_score":
            candidate_id = f"__pre_score__:{disposition}"
            source_id = "opaque:excluded-before-scoring"
            component_scores: dict[str, Any] = {}
            token_cost = 0
            privacy_class = "restricted"
        else:
            candidate_id = str(receipt.get("candidate_id") or "").strip()
            source_id = str(receipt.get("source_id") or "").strip()
            component_scores = _json_object(
                receipt.get("component_scores", {}), "component_scores"
            )
            token_cost = int(receipt.get("token_cost", 0))
            privacy_class = str(receipt.get("privacy_class") or "").strip()
        if not candidate_id or not source_id:
            raise ValueError("selection receipt identity is incomplete")
        if candidate_id in seen:
            raise ValueError("selection receipt candidate identity is duplicated")
        if privacy_class not in _PRIVACY_ORDER:
            raise ValueError("selection receipt privacy class is invalid")
        if token_cost < 0:
            raise ValueError("selection receipt token cost cannot be negative")
        seen.add(candidate_id)
        explanation = {
            key: receipt[key]
            for key in ("stage", "section", "score_micros", "rendering", "reason_codes", "count")
            if key in receipt
        }
        normalized.append(
            {
                "candidate_id": candidate_id,
                "disposition": disposition,
                "source_id": source_id,
                "component_scores": component_scores,
                "token_cost": token_cost,
                "explanation": json.loads(_canonical(explanation)),
                "privacy_class": privacy_class,
            }
        )
    return sorted(normalized, key=lambda row: (row["candidate_id"], row["disposition"]))


def _variant_privacy(receipts: list[dict[str, Any]]) -> str:
    included = [
        row["privacy_class"]
        for row in receipts
        if row["disposition"] in {"included_mandatory", "included_ranked", "summarized_dependency"}
    ]
    # Task contracts are operational data even when all selected evidence is public.
    return max(["internal", *included], key=_PRIVACY_ORDER.__getitem__)


def _receipt_summary(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    included_dispositions = {
        "included_mandatory",
        "included_ranked",
        "summarized_dependency",
    }
    included_count = 0
    exclusion_summary: dict[str, int] = {}
    for receipt in receipts:
        disposition = receipt["disposition"]
        if disposition in included_dispositions:
            included_count += 1
        else:
            exclusion_summary[disposition] = exclusion_summary.get(disposition, 0) + 1
    return {
        "included_count": included_count,
        "excluded_count": sum(exclusion_summary.values()),
        "exclusion_summary": dict(sorted(exclusion_summary.items())),
    }


def _pack_variant_body(
    *,
    variant_id: str,
    selection: dict[str, Any],
    consumer_pack: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    coverage = {
        "selection_digest": _required_digest(
            selection.get("selection_digest"), "selection_digest"
        ),
        "coverage": _json_object(selection.get("coverage", {}), "coverage"),
        "warnings": list(selection.get("warnings", [])),
        "blocking_reasons": list(selection.get("blocking_reasons", [])),
    }
    return {
        "variant_id": variant_id,
        "mode": str(selection["compiler_mode"]),
        "pack_digest": _required_digest(
            consumer_pack.get("context_pack_digest"), "context_pack_digest"
        ),
        "token_count": int(selection["budget"]["used_tokens"]),
        "coverage": coverage,
        "bounded_preview": None,
        "preview_redacted": 0,
        "privacy_class": _variant_privacy(receipts),
        "retention_policy": None,
    }


def _normalize_alternative_variants(
    value: Any, *, primary_selection: dict[str, Any]
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("alternative_variants must be a list")
    if len(value) > 3:
        raise ValueError("alternative_variants exceeds 3 items")
    normalized = []
    seen: set[str] = set()
    shared_fields = (
        "contract_digest",
        "profile_digest",
        "envelope_digest",
        "snapshot_digest",
        "compiler_version",
    )
    for item in value:
        row = _json_object(item, "alternative variant")
        variant_id = str(row.get("variant_id") or "").strip()
        selection = _json_object(row.get("selection"), "alternative selection")
        consumer_pack = _json_object(row.get("consumer_pack"), "alternative consumer_pack")
        mode = str(selection.get("compiler_mode") or "").strip()
        if variant_id != f"mode:{mode}" or mode == primary_selection.get("compiler_mode"):
            raise ValueError("alternative variant identity does not match its compiler mode")
        if variant_id in seen:
            raise ValueError("alternative variant identity is duplicated")
        if any(selection.get(field) != primary_selection.get(field) for field in shared_fields):
            raise ValueError("alternative variant does not share the primary compilation state")
        receipts = _receipt_rows(selection)
        seen.add(variant_id)
        normalized.append(
            {
                "variant_id": variant_id,
                "selection": selection,
                "consumer_pack": consumer_pack,
                "receipts": receipts,
            }
        )
    return sorted(normalized, key=lambda row: row["variant_id"])


def _expected_body(
    *,
    compilation_id: str,
    project_id: int,
    task_contract_id: int,
    selection: dict[str, Any],
    consumer_pack: dict[str, Any],
    receipts: list[dict[str, Any]],
    authority_grant: dict[str, Any],
    alternative_variants: list[dict[str, Any]],
) -> dict[str, Any]:
    variants = [
        _pack_variant_body(
            variant_id="primary",
            selection=selection,
            consumer_pack=consumer_pack,
            receipts=receipts,
        )
    ]
    variant_receipts = []
    for alternative in alternative_variants:
        variants.append(
            _pack_variant_body(
                variant_id=alternative["variant_id"],
                selection=alternative["selection"],
                consumer_pack=alternative["consumer_pack"],
                receipts=alternative["receipts"],
            )
        )
        variant_receipts.append(
            {
                "variant_id": alternative["variant_id"],
                "receipts": alternative["receipts"],
            }
        )
    compilation = {
        "compilation_id": compilation_id,
        "project_id": int(project_id),
        "task_contract_id": int(task_contract_id),
        "authority_grant_id": int(authority_grant["authority_grant_id"]),
        "authority_grant_digest": _required_digest(
            authority_grant.get("capability_digest"), "authority_grant_digest"
        ),
        "contract_digest": _required_digest(selection.get("contract_digest"), "contract_digest"),
        "profile_digest": _required_digest(selection.get("profile_digest"), "profile_digest"),
        "envelope_digest": _required_digest(selection.get("envelope_digest"), "envelope_digest"),
        "snapshot_digest": _required_digest(selection.get("snapshot_digest"), "snapshot_digest"),
        "compiler_version": str(selection["compiler_version"]),
        "compiler_mode": str(selection["compiler_mode"]),
        "status": str(selection["status"]),
        "effective_budget": _json_object(selection.get("budget", {}), "budget"),
    }
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "compilation": compilation,
        "candidate_receipts": receipts,
        "pack_variants": variants,
        "variant_candidate_receipts": variant_receipts,
    }


def _stored_body(conn: sqlite3.Connection, compilation_row: sqlite3.Row) -> dict[str, Any]:
    grant_row = conn.execute(
        "SELECT capability_digest FROM context_authority_grants WHERE id = ?",
        (int(compilation_row["authority_grant_id"]),),
    ).fetchone()
    if grant_row is None:
        raise ValueError("compilation authority grant is missing")
    candidate_rows = conn.execute(
        """
        SELECT candidate_id, disposition, source_id, component_scores_json,
               token_cost, explanation_json, privacy_class
        FROM context_candidate_receipts
        WHERE compilation_id = ?
        ORDER BY candidate_id, disposition
        """,
        (int(compilation_row["id"]),),
    ).fetchall()
    variant_rows = conn.execute(
        """
        SELECT variant_id, mode, pack_digest, token_count, coverage_json,
               bounded_preview, preview_redacted, privacy_class,
               retention_policy_id, retention_policy_digest
        FROM context_pack_variants
        WHERE compilation_id = ?
        ORDER BY CASE WHEN variant_id = 'primary' THEN 0 ELSE 1 END, variant_id
        """,
        (int(compilation_row["id"]),),
    ).fetchall()
    variant_candidate_rows = conn.execute(
        """
        SELECT v.variant_id, r.candidate_id, r.disposition, r.source_id,
               r.component_scores_json, r.token_cost, r.explanation_json,
               r.privacy_class
        FROM context_pack_variants v
        LEFT JOIN context_variant_candidate_receipts r ON r.pack_variant_id = v.id
        WHERE v.compilation_id = ? AND v.variant_id != 'primary'
        ORDER BY v.variant_id, r.candidate_id, r.disposition
        """,
        (int(compilation_row["id"]),),
    ).fetchall()
    variant_candidate_receipts: dict[str, list[dict[str, Any]]] = {}
    for row in variant_candidate_rows:
        rows = variant_candidate_receipts.setdefault(row["variant_id"], [])
        if row["candidate_id"] is not None:
            rows.append(
                {
                    "candidate_id": row["candidate_id"],
                    "disposition": row["disposition"],
                    "source_id": row["source_id"],
                    "component_scores": json.loads(row["component_scores_json"]),
                    "token_cost": int(row["token_cost"]),
                    "explanation": json.loads(row["explanation_json"]),
                    "privacy_class": row["privacy_class"],
                }
            )
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "compilation": {
            "compilation_id": compilation_row["compilation_id"],
            "project_id": int(compilation_row["project_id"]),
            "task_contract_id": int(compilation_row["task_contract_id"]),
            "authority_grant_id": int(compilation_row["authority_grant_id"]),
            "authority_grant_digest": grant_row["capability_digest"],
            "contract_digest": compilation_row["contract_digest"],
            "profile_digest": compilation_row["profile_digest"],
            "envelope_digest": compilation_row["envelope_digest"],
            "snapshot_digest": compilation_row["snapshot_digest"],
            "compiler_version": compilation_row["compiler_version"],
            "compiler_mode": compilation_row["compiler_mode"],
            "status": compilation_row["status"],
            "effective_budget": json.loads(compilation_row["effective_budget_json"]),
        },
        "candidate_receipts": [
            {
                "candidate_id": row["candidate_id"],
                "disposition": row["disposition"],
                "source_id": row["source_id"],
                "component_scores": json.loads(row["component_scores_json"]),
                "token_cost": int(row["token_cost"]),
                "explanation": json.loads(row["explanation_json"]),
                "privacy_class": row["privacy_class"],
            }
            for row in candidate_rows
        ],
        "pack_variants": [
            {
                "variant_id": row["variant_id"],
                "mode": row["mode"],
                "pack_digest": row["pack_digest"],
                "token_count": int(row["token_count"]),
                "coverage": json.loads(row["coverage_json"]),
                "bounded_preview": row["bounded_preview"],
                "preview_redacted": int(row["preview_redacted"]),
                "privacy_class": row["privacy_class"],
                "retention_policy": (
                    None
                    if row["retention_policy_id"] is None
                    else {
                        "id": row["retention_policy_id"],
                        "digest": row["retention_policy_digest"],
                    }
                ),
            }
            for row in variant_rows
        ],
        "variant_candidate_receipts": [
            {"variant_id": variant_id, "receipts": variant_candidate_receipts[variant_id]}
            for variant_id in sorted(variant_candidate_receipts)
        ],
    }


def persist_compilation_receipt(
    conn: sqlite3.Connection,
    *,
    project: str,
    task_contract_id: int,
    selection: dict[str, Any],
    consumer_pack: dict[str, Any],
    authority_grant: dict[str, Any],
    alternative_variants: list[dict[str, Any]] | None = None,
    precommit_verifier: Callable[[sqlite3.Connection], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Atomically persist or verify one metadata-only compilation receipt."""
    if conn.in_transaction:
        raise ValueError("compilation receipt persistence requires an idle connection")
    db.init_schema(conn)
    normalized_selection = _json_object(selection, "selection")
    normalized_pack = _json_object(consumer_pack, "consumer_pack")
    normalized_grant = _json_object(authority_grant, "authority_grant")
    normalized_alternatives = _normalize_alternative_variants(
        alternative_variants, primary_selection=normalized_selection
    )
    from .context_selection import build_consumer_context_pack

    if build_consumer_context_pack(normalized_selection) != normalized_pack:
        raise ValueError("primary context pack does not match its selection receipt")
    for alternative in normalized_alternatives:
        if (
            build_consumer_context_pack(alternative["selection"])
            != alternative["consumer_pack"]
        ):
            raise ValueError("alternative context pack does not match its selection receipt")
    status = str(normalized_selection.get("status") or "")
    if status not in {"complete", "abstained"}:
        raise ValueError("only complete or abstained selections can be persisted")
    receipts = _receipt_rows(normalized_selection)
    identity = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "project": str(project),
        "task_contract_id": int(task_contract_id),
        "selection_digest": _required_digest(
            normalized_selection.get("selection_digest"), "selection_digest"
        ),
        "pack_digest": _required_digest(
            normalized_pack.get("context_pack_digest"), "context_pack_digest"
        ),
        "authority_grant_digest": _required_digest(
            normalized_grant.get("capability_digest"), "authority_grant_digest"
        ),
        "alternative_variants": [
            {
                "variant_id": row["variant_id"],
                "selection_digest": _required_digest(
                    row["selection"].get("selection_digest"), "selection_digest"
                ),
                "pack_digest": _required_digest(
                    row["consumer_pack"].get("context_pack_digest"),
                    "context_pack_digest",
                ),
            }
            for row in normalized_alternatives
        ],
    }
    compilation_id = f"ctxc-{_digest(identity)}"
    created_at = db.now_iso()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if precommit_verifier is not None:
            verification = precommit_verifier(conn)
            if (
                not isinstance(verification, dict)
                or verification.get("status") != "stable"
            ):
                raise CompilationStateChanged(
                    verification
                    if isinstance(verification, dict)
                    else {
                        "status": "state_changed_retry",
                        "changed": ["snapshot_unavailable"],
                    }
                )
        project_row = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (str(project),)
        ).fetchone()
        if project_row is None:
            raise ValueError(f"unknown project: {project}")
        project_id = int(project_row["id"])
        contract_row = conn.execute(
            """
            SELECT project_id, canonical_json, digest
            FROM task_contracts WHERE id = ?
            """,
            (int(task_contract_id),),
        ).fetchone()
        if (
            contract_row is None
            or int(contract_row["project_id"]) != project_id
            or contract_row["digest"] != normalized_selection.get("contract_digest")
        ):
            raise PermissionError("compilation receipt does not match its project contract")
        contract_body = json.loads(contract_row["canonical_json"])
        if normalized_selection.get("compiler_mode") != contract_body.get("compiler_mode"):
            raise PermissionError("primary context mode is not authorized by its contract")
        authorized_alternatives = sorted(
            f"mode:{mode}" for mode in contract_body.get("comparison_modes", [])
        )
        actual_alternatives = [row["variant_id"] for row in normalized_alternatives]
        if actual_alternatives != authorized_alternatives:
            raise PermissionError("comparison context variants do not match their contract")
        expected = _expected_body(
            compilation_id=compilation_id,
            project_id=project_id,
            task_contract_id=int(task_contract_id),
            selection=normalized_selection,
            consumer_pack=normalized_pack,
            receipts=receipts,
            authority_grant=normalized_grant,
            alternative_variants=normalized_alternatives,
        )
        expected_digest = _digest(expected)
        existing = conn.execute(
            "SELECT * FROM context_compilations WHERE compilation_id = ?",
            (compilation_id,),
        ).fetchone()
        if existing is not None:
            if existing["status"] not in _TERMINAL_STATUSES:
                raise RuntimeError("existing compilation receipt is not terminal")
            stored = _stored_body(conn, existing)
            if stored != expected or existing["receipt_digest"] != _digest(stored):
                raise ValueError("persisted compilation receipt failed its integrity check")
            conn.commit()
            return {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "compilation_id": compilation_id,
                "receipt_digest": existing["receipt_digest"],
                "status": existing["status"],
                "idempotent_replay": True,
            }

        compilation_row_id = int(
            conn.execute(
                """
                INSERT INTO context_compilations(
                    compilation_id, project_id, task_contract_id, authority_grant_id,
                    contract_digest,
                    profile_digest, envelope_digest, snapshot_digest, compiler_version,
                    compiler_mode, status, effective_budget_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'building', ?, ?)
                """,
                (
                    compilation_id,
                    project_id,
                    int(task_contract_id),
                    expected["compilation"]["authority_grant_id"],
                    expected["compilation"]["contract_digest"],
                    expected["compilation"]["profile_digest"],
                    expected["compilation"]["envelope_digest"],
                    expected["compilation"]["snapshot_digest"],
                    expected["compilation"]["compiler_version"],
                    expected["compilation"]["compiler_mode"],
                    _canonical(expected["compilation"]["effective_budget"]),
                    created_at,
                ),
            ).lastrowid
        )
        for row in receipts:
            conn.execute(
                """
                INSERT INTO context_candidate_receipts(
                    compilation_id, candidate_id, disposition, source_id,
                    component_scores_json, token_cost, explanation_json,
                    privacy_class, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    compilation_row_id,
                    row["candidate_id"],
                    row["disposition"],
                    row["source_id"],
                    _canonical(row["component_scores"]),
                    row["token_cost"],
                    _canonical(row["explanation"]),
                    row["privacy_class"],
                    created_at,
                ),
            )
        receipts_by_variant = {
            item["variant_id"]: item["receipts"]
            for item in expected["variant_candidate_receipts"]
        }
        for variant in expected["pack_variants"]:
            pack_variant_id = int(
                conn.execute(
                    """
                    INSERT INTO context_pack_variants(
                        compilation_id, project_id, variant_id, mode, pack_digest,
                        token_count, coverage_json, bounded_preview, preview_redacted,
                        privacy_class, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
                    """,
                    (
                        compilation_row_id,
                        project_id,
                        variant["variant_id"],
                        variant["mode"],
                        variant["pack_digest"],
                        variant["token_count"],
                        _canonical(variant["coverage"]),
                        variant["privacy_class"],
                        created_at,
                    ),
                ).lastrowid
            )
            for row in receipts_by_variant.get(variant["variant_id"], []):
                conn.execute(
                    """
                    INSERT INTO context_variant_candidate_receipts(
                        pack_variant_id, compilation_id, candidate_id, disposition,
                        source_id, component_scores_json, token_cost,
                        explanation_json, privacy_class, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pack_variant_id,
                        compilation_row_id,
                        row["candidate_id"],
                        row["disposition"],
                        row["source_id"],
                        _canonical(row["component_scores"]),
                        row["token_cost"],
                        _canonical(row["explanation"]),
                        row["privacy_class"],
                        created_at,
                    ),
                )
        finalized_at = db.now_iso()
        conn.execute(
            """
            UPDATE context_compilations
            SET status = ?, receipt_digest = ?, finalized_at = ?
            WHERE id = ?
            """,
            (status, expected_digest, finalized_at, compilation_row_id),
        )
        stored = conn.execute(
            "SELECT * FROM context_compilations WHERE id = ?", (compilation_row_id,)
        ).fetchone()
        if _stored_body(conn, stored) != expected:
            raise RuntimeError("compilation receipt verification failed before commit")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "compilation_id": compilation_id,
        "receipt_digest": expected_digest,
        "status": status,
        "idempotent_replay": False,
    }


def _bounded_json_object(value: Any, name: str) -> dict[str, Any]:
    normalized = _json_object(value, name)
    if len(_canonical(normalized).encode("utf-8")) > 1_048_576:
        raise ValueError(f"{name} exceeds the 1 MiB receipt limit")
    return normalized


def _normalized_attributions(
    attributions: Any, *, outcome_level: str
) -> list[dict[str, Any]]:
    if not isinstance(attributions, list):
        raise TypeError("attributions must be a list")
    if len(attributions) > 1_000:
        raise ValueError("attributions exceed the 1,000 edge limit")
    normalized = []
    seen: set[tuple[str, str]] = set()
    for value in attributions:
        if not isinstance(value, dict):
            raise TypeError("attribution must be an object")
        candidate_id = str(value.get("candidate_id") or "").strip()
        assessment = str(value.get("assessment") or "").strip()
        level = str(value.get("attribution_level") or "").strip()
        evidence = _bounded_json_object(value.get("evidence", {}), "attribution evidence")
        if not candidate_id or len(candidate_id) > 512:
            raise ValueError("attribution candidate_id is invalid")
        if assessment not in _ASSESSMENTS:
            raise ValueError("attribution assessment is invalid")
        if level not in _ATTRIBUTION_LEVELS:
            raise ValueError("attribution level is invalid")
        if _ATTRIBUTION_LEVELS[level] > _ATTRIBUTION_LEVELS[outcome_level]:
            raise PermissionError("attribution exceeds outcome authority")
        if level != "observed" and not evidence:
            raise ValueError("correlated attribution requires evidence")
        identity = (candidate_id, assessment)
        if identity in seen:
            raise ValueError("attribution identity is duplicated")
        seen.add(identity)
        normalized.append(
            {
                "candidate_id": candidate_id,
                "assessment": assessment,
                "attribution_level": level,
                "evidence": evidence,
            }
        )
    return sorted(
        normalized,
        key=lambda row: (row["candidate_id"], row["assessment"], row["attribution_level"]),
    )


def _outcome_body(
    *,
    project_id: int,
    compilation_id: str,
    outcome_id: str,
    task_status: str,
    attribution_level: str,
    evidence: dict[str, Any],
    acceptance_results: dict[str, Any],
    elapsed_ms: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    actor_type: str,
    actor_id: str,
    authority_grant_id: int | None,
    capability_digest: str | None,
    attributions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "rta-smriti.context-outcome/v1",
        "project_id": int(project_id),
        "compilation_id": compilation_id,
        "outcome_id": outcome_id,
        "task_status": task_status,
        "attribution_level": attribution_level,
        "evidence": evidence,
        "acceptance_results": acceptance_results,
        "elapsed_ms": elapsed_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "authority_grant_id": authority_grant_id,
        "capability_digest": capability_digest,
        "attributions": attributions,
    }


def _stored_outcome_body(
    conn: sqlite3.Connection, outcome_row: sqlite3.Row, *, compilation_public_id: str
) -> dict[str, Any]:
    edges = conn.execute(
        """
        SELECT candidate_id, assessment, attribution_level, evidence_json
        FROM context_attribution_edges
        WHERE outcome_id = ?
        ORDER BY candidate_id, assessment, attribution_level
        """,
        (int(outcome_row["id"]),),
    ).fetchall()
    capability_digest = None
    if outcome_row["authority_grant_id"] is not None:
        grant = conn.execute(
            "SELECT capability_digest FROM context_authority_grants WHERE id = ?",
            (int(outcome_row["authority_grant_id"]),),
        ).fetchone()
        if grant is None:
            raise RuntimeError("outcome authority grant is missing")
        capability_digest = str(grant["capability_digest"])
    return _outcome_body(
        project_id=int(outcome_row["project_id"]),
        compilation_id=compilation_public_id,
        outcome_id=outcome_row["outcome_id"],
        task_status=outcome_row["task_status"],
        attribution_level=outcome_row["attribution_level"],
        evidence=json.loads(outcome_row["evidence_json"]),
        acceptance_results=json.loads(outcome_row["acceptance_results_json"]),
        elapsed_ms=outcome_row["elapsed_ms"],
        input_tokens=outcome_row["input_tokens"],
        output_tokens=outcome_row["output_tokens"],
        actor_type=outcome_row["actor_type"],
        actor_id=outcome_row["actor_id"],
        authority_grant_id=(
            None
            if outcome_row["authority_grant_id"] is None
            else int(outcome_row["authority_grant_id"])
        ),
        capability_digest=capability_digest,
        attributions=[
            {
                "candidate_id": row["candidate_id"],
                "assessment": row["assessment"],
                "attribution_level": row["attribution_level"],
                "evidence": json.loads(row["evidence_json"]),
            }
            for row in edges
        ],
    )


def record_context_outcome(
    conn: sqlite3.Connection,
    *,
    project: str,
    compilation_id: str,
    outcome_id: str,
    task_status: str,
    attribution_level: str,
    evidence: dict[str, Any],
    acceptance_results: dict[str, Any],
    actor_type: str,
    actor_id: str,
    attributions: list[dict[str, Any]],
    elapsed_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    capability_token: str | None = None,
    authority_secret: bytes | None = None,
    principal_type: str | None = None,
    principal_id: str | None = None,
    session_id: str | None = None,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Append an idempotent outcome without allowing self-asserted operator authority."""
    if conn.in_transaction:
        raise ValueError("outcome recording requires an idle connection")
    db.init_schema(conn)
    project = str(project or "").strip()
    compilation_id = str(compilation_id or "").strip()
    outcome_id = str(outcome_id or "").strip()
    task_status = str(task_status or "").strip()
    attribution_level = str(attribution_level or "").strip()
    actor_type = str(actor_type or "").strip()
    actor_id = str(actor_id or "").strip()
    if not project or not compilation_id:
        raise ValueError("project and compilation_id are required")
    if not outcome_id or len(outcome_id) > 200:
        raise ValueError("outcome_id is invalid")
    if task_status not in _TASK_STATUSES:
        raise ValueError("task_status is invalid")
    if attribution_level not in _ATTRIBUTION_LEVELS:
        raise ValueError("attribution_level is invalid")
    if actor_type not in _ACTOR_TYPES or not actor_id or len(actor_id) > 300:
        raise ValueError("outcome actor is invalid")
    capability_context = (
        capability_token,
        authority_secret,
        principal_type,
        principal_id,
        session_id,
    )
    if attribution_level == "operator_confirmed":
        if actor_type != "operator" or any(value is None for value in capability_context):
            raise PermissionError(
                "operator-confirmed outcomes require an authenticated operator capability"
            )
    elif any(value is not None for value in capability_context):
        raise ValueError("capability context is only accepted for operator-confirmed outcomes")
    normalized_evidence = _bounded_json_object(evidence, "outcome evidence")
    normalized_acceptance = _bounded_json_object(
        acceptance_results, "acceptance results"
    )
    if attribution_level == "correlated" and not normalized_evidence:
        raise ValueError("correlated outcomes require evidence")
    metrics = []
    for name, value in (
        ("elapsed_ms", elapsed_ms),
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
    ):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ValueError(f"{name} must be a non-negative integer or null")
        metrics.append(value)
    normalized_attributions = _normalized_attributions(
        attributions, outcome_level=attribution_level
    )
    created_at = db.now_iso()
    try:
        conn.execute("BEGIN IMMEDIATE")
        project_row = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (project,)
        ).fetchone()
        if project_row is None:
            raise ValueError(f"unknown project: {project}")
        project_id = int(project_row["id"])
        compilation = conn.execute(
            """
            SELECT id, compilation_id, task_contract_id, status, receipt_digest
            FROM context_compilations
            WHERE compilation_id = ? AND project_id = ?
            """,
            (compilation_id, project_id),
        ).fetchone()
        if (
            compilation is None
            or compilation["status"] not in _TERMINAL_STATUSES
            or not compilation["receipt_digest"]
        ):
            raise PermissionError("outcome requires a terminal project compilation receipt")
        authority_grant = None
        if attribution_level == "operator_confirmed":
            from .context_authorization import load_authorized_context

            authorized = load_authorized_context(
                conn,
                project=project,
                task_contract_id=int(compilation["task_contract_id"]),
                capability_token=capability_token,
                authority_secret=authority_secret,
                principal_type=principal_type,
                principal_id=principal_id,
                session_id=session_id,
                required_scope="confirm:outcome",
                now_epoch_ms=now_epoch_ms,
            )
            authority_grant = authorized["authority_grant"]
            if (
                authority_grant is None
                or authority_grant["principal_type"] != "operator"
                or authority_grant["principal_id"] != actor_id
            ):
                raise PermissionError("operator outcome authority does not match its actor")
        receipt_rows = conn.execute(
            """
            SELECT id, candidate_id, disposition
            FROM context_candidate_receipts WHERE compilation_id = ?
            """,
            (int(compilation["id"]),),
        ).fetchall()
        included = {
            row["candidate_id"]: int(row["id"])
            for row in receipt_rows
            if row["disposition"]
            in {"included_mandatory", "included_ranked", "summarized_dependency"}
        }
        for attribution in normalized_attributions:
            if attribution["candidate_id"] not in included:
                raise PermissionError("outcome attribution requires included context")
        expected = _outcome_body(
            project_id=project_id,
            compilation_id=compilation_id,
            outcome_id=outcome_id,
            task_status=task_status,
            attribution_level=attribution_level,
            evidence=normalized_evidence,
            acceptance_results=normalized_acceptance,
            elapsed_ms=metrics[0],
            input_tokens=metrics[1],
            output_tokens=metrics[2],
            actor_type=actor_type,
            actor_id=actor_id,
            authority_grant_id=(
                None
                if authority_grant is None
                else int(authority_grant["authority_grant_id"])
            ),
            capability_digest=(
                None
                if authority_grant is None
                else str(authority_grant["capability_digest"])
            ),
            attributions=normalized_attributions,
        )
        outcome_digest = _digest(expected)
        existing = conn.execute(
            "SELECT * FROM context_outcomes WHERE project_id = ? AND outcome_id = ?",
            (project_id, outcome_id),
        ).fetchone()
        if existing is not None:
            if _stored_outcome_body(
                conn, existing, compilation_public_id=compilation_id
            ) != expected:
                raise ValueError("outcome identity already has different content")
            conn.commit()
            return {
                "outcome_id": outcome_id,
                "outcome_digest": outcome_digest,
                "authority_grant_id": (
                    None
                    if authority_grant is None
                    else int(authority_grant["authority_grant_id"])
                ),
                "idempotent_replay": True,
            }
        outcome_row_id = int(
            conn.execute(
                """
                INSERT INTO context_outcomes(
                    project_id, compilation_id, authority_grant_id, outcome_id, task_status,
                    attribution_level, evidence_json, acceptance_results_json,
                    elapsed_ms, input_tokens, output_tokens, created_at,
                    actor_type, actor_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    int(compilation["id"]),
                    (
                        None
                        if authority_grant is None
                        else int(authority_grant["authority_grant_id"])
                    ),
                    outcome_id,
                    task_status,
                    attribution_level,
                    _canonical(normalized_evidence),
                    _canonical(normalized_acceptance),
                    metrics[0],
                    metrics[1],
                    metrics[2],
                    created_at,
                    actor_type,
                    actor_id,
                ),
            ).lastrowid
        )
        for attribution in normalized_attributions:
            conn.execute(
                """
                INSERT INTO context_attribution_edges(
                    outcome_id, compilation_id, candidate_receipt_id,
                    candidate_id, assessment, attribution_level,
                    evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome_row_id,
                    int(compilation["id"]),
                    included[attribution["candidate_id"]],
                    attribution["candidate_id"],
                    attribution["assessment"],
                    attribution["attribution_level"],
                    _canonical(attribution["evidence"]),
                    created_at,
                ),
            )
        stored = conn.execute(
            "SELECT * FROM context_outcomes WHERE id = ?", (outcome_row_id,)
        ).fetchone()
        if _stored_outcome_body(
            conn, stored, compilation_public_id=compilation_id
        ) != expected:
            raise RuntimeError("outcome receipt verification failed before commit")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "outcome_id": outcome_id,
        "outcome_digest": outcome_digest,
        "authority_grant_id": (
            None
            if authority_grant is None
            else int(authority_grant["authority_grant_id"])
        ),
        "idempotent_replay": False,
    }


def explain_context_compilation(
    conn: sqlite3.Connection,
    *,
    project: str,
    compilation_id: str,
    capability_token: str,
    authority_secret: bytes,
    principal_type: str,
    principal_id: str,
    session_id: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Return a capability-bound explanation without excluded evidence or payloads."""
    if conn.in_transaction:
        raise ValueError("context explanation requires an idle connection")
    db.init_schema(conn)
    selected_project = str(project or "").strip()
    selected_compilation = str(compilation_id or "").strip()
    if not selected_project or not selected_compilation:
        raise ValueError("project and compilation_id are required")
    try:
        conn.execute("BEGIN")
        project_row = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (selected_project,)
        ).fetchone()
        if project_row is None:
            raise ValueError(f"unknown project: {selected_project}")
        compilation = conn.execute(
            """
            SELECT * FROM context_compilations
            WHERE project_id = ? AND compilation_id = ?
            """,
            (int(project_row["id"]), selected_compilation),
        ).fetchone()
        if compilation is None or compilation["status"] not in _TERMINAL_STATUSES:
            raise ValueError("unknown terminal context compilation")

        from .context_authorization import load_authorized_context

        authorization = load_authorized_context(
            conn,
            project=selected_project,
            task_contract_id=int(compilation["task_contract_id"]),
            capability_token=capability_token,
            authority_secret=authority_secret,
            principal_type=principal_type,
            principal_id=principal_id,
            session_id=session_id,
            required_scope="compile:context",
            now_epoch_ms=now_epoch_ms,
        )
        current_grant = authorization["authority_grant"]
        if current_grant is None:
            raise PermissionError("context explanation requires a host capability")
        original_grant = conn.execute(
            """
            SELECT g.claims_json, r.id AS revocation_id
            FROM context_authority_grants g
            LEFT JOIN context_authority_revocations r
              ON r.authority_grant_id = g.id
            WHERE g.id = ?
            """,
            (int(compilation["authority_grant_id"]),),
        ).fetchone()
        if original_grant is None:
            raise ValueError("compilation authority grant is missing")
        if original_grant["revocation_id"] is not None:
            raise PermissionError("compilation capability has been revoked")
        original_claims = json.loads(original_grant["claims_json"])
        if any(
            original_claims.get(field) != current_grant[field]
            for field in ("principal_type", "principal_id", "session_id")
        ):
            raise PermissionError("capability does not match the compilation principal session")
        stored = _stored_body(conn, compilation)
        receipt_integrity_verified = (
            compilation["receipt_digest"] is not None
            and hmac.compare_digest(str(compilation["receipt_digest"]), _digest(stored))
        )
        if not receipt_integrity_verified:
            raise ValueError("persisted compilation receipt failed its integrity check")

        included_dispositions = {
            "included_mandatory",
            "included_ranked",
            "summarized_dependency",
        }
        included = []
        exclusion_summary: dict[str, int] = {}
        for receipt in stored["candidate_receipts"]:
            disposition = receipt["disposition"]
            if disposition in included_dispositions:
                included.append(
                    {
                        "candidate_id": receipt["candidate_id"],
                        "source_id": receipt["source_id"],
                        "disposition": disposition,
                        "token_cost": receipt["token_cost"],
                        "section": receipt["explanation"].get("section"),
                        "rendering": receipt["explanation"].get("rendering"),
                        "reason_codes": list(
                            receipt["explanation"].get("reason_codes", [])
                        ),
                    }
                )
            else:
                exclusion_summary[disposition] = exclusion_summary.get(disposition, 0) + 1

        outcome_rows = conn.execute(
            """
            SELECT * FROM context_outcomes
            WHERE project_id = ? AND compilation_id = ?
            ORDER BY created_at, id
            """,
            (int(project_row["id"]), int(compilation["id"])),
        ).fetchall()
        outcomes = []
        for row in outcome_rows:
            body = _stored_outcome_body(
                conn, row, compilation_public_id=selected_compilation
            )
            outcomes.append(
                {
                    "outcome_id": body["outcome_id"],
                    "outcome_digest": _digest(body),
                    "task_status": body["task_status"],
                    "attribution_level": body["attribution_level"],
                    "acceptance_result_count": len(body["acceptance_results"]),
                    "elapsed_ms": body["elapsed_ms"],
                    "input_tokens": body["input_tokens"],
                    "output_tokens": body["output_tokens"],
                    "attributions": [
                        {
                            "candidate_id": edge["candidate_id"],
                            "assessment": edge["assessment"],
                            "attribution_level": edge["attribution_level"],
                        }
                        for edge in body["attributions"]
                    ],
                }
            )
        variant_receipts = {
            "primary": stored["candidate_receipts"],
            **{
                item["variant_id"]: item["receipts"]
                for item in stored["variant_candidate_receipts"]
            },
        }
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    return {
        "schema_version": "rta-smriti.context-explanation/v1",
        "receipt_integrity_verified": receipt_integrity_verified,
        "compilation": {
            "compilation_id": selected_compilation,
            "status": stored["compilation"]["status"],
            "compiler_version": stored["compilation"]["compiler_version"],
            "compiler_mode": stored["compilation"]["compiler_mode"],
            "snapshot_digest": stored["compilation"]["snapshot_digest"],
            "receipt_digest": str(compilation["receipt_digest"]),
        },
        "selection": {
            "included": included,
            "included_count": len(included),
            "excluded_count": sum(exclusion_summary.values()),
            "exclusion_summary": dict(sorted(exclusion_summary.items())),
        },
        "pack_variants": [
            {
                "variant_id": variant["variant_id"],
                "mode": variant["mode"],
                "pack_digest": variant["pack_digest"],
                "token_count": variant["token_count"],
                "coverage": variant["coverage"],
                "privacy_class": variant["privacy_class"],
                "selection_summary": _receipt_summary(
                    variant_receipts.get(variant["variant_id"], [])
                ),
            }
            for variant in stored["pack_variants"]
        ],
        "outcomes": outcomes,
    }


def audit_context_compilation(
    conn: sqlite3.Connection,
    *,
    project: str,
    compilation_id: str,
    capability_token: str,
    authority_secret: bytes,
    principal_type: str,
    principal_id: str,
    session_id: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Return full metadata receipts to an authenticated operator, never pack payloads."""
    if conn.in_transaction:
        raise ValueError("context audit requires an idle connection")
    db.init_schema(conn)
    selected_project = str(project or "").strip()
    selected_compilation = str(compilation_id or "").strip()
    if not selected_project or not selected_compilation:
        raise ValueError("project and compilation_id are required")
    try:
        conn.execute("BEGIN")
        project_row = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (selected_project,)
        ).fetchone()
        if project_row is None:
            raise ValueError(f"unknown project: {selected_project}")
        compilation = conn.execute(
            """
            SELECT * FROM context_compilations
            WHERE project_id = ? AND compilation_id = ?
            """,
            (int(project_row["id"]), selected_compilation),
        ).fetchone()
        if compilation is None or compilation["status"] not in _TERMINAL_STATUSES:
            raise ValueError("unknown terminal context compilation")

        from .context_authorization import load_authorized_context

        authorization = load_authorized_context(
            conn,
            project=selected_project,
            task_contract_id=int(compilation["task_contract_id"]),
            capability_token=capability_token,
            authority_secret=authority_secret,
            principal_type=principal_type,
            principal_id=principal_id,
            session_id=session_id,
            required_scope="audit:context",
            now_epoch_ms=now_epoch_ms,
        )
        grant = authorization["authority_grant"]
        if grant is None or grant["principal_type"] != "operator":
            raise PermissionError("context audit requires operator authority")
        stored = _stored_body(conn, compilation)
        receipt_digest = _digest(stored)
        if compilation["receipt_digest"] is None or not hmac.compare_digest(
            str(compilation["receipt_digest"]), receipt_digest
        ):
            raise ValueError("persisted compilation receipt failed its integrity check")
        outcome_rows = conn.execute(
            """
            SELECT * FROM context_outcomes
            WHERE project_id = ? AND compilation_id = ?
            ORDER BY created_at, id
            """,
            (int(project_row["id"]), int(compilation["id"])),
        ).fetchall()
        outcomes = [
            _stored_outcome_body(
                conn, row, compilation_public_id=selected_compilation
            )
            for row in outcome_rows
        ]
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    compilation_metadata = dict(stored["compilation"])
    compilation_metadata.pop("authority_grant_digest", None)
    variants = []
    for variant in stored["pack_variants"]:
        metadata = dict(variant)
        metadata.pop("bounded_preview", None)
        variants.append(metadata)
    return {
        "schema_version": "rta-smriti.context-audit/v1",
        "receipt_integrity_verified": True,
        "receipt_digest": receipt_digest,
        "compilation": compilation_metadata,
        "candidate_receipts": stored["candidate_receipts"],
        "variant_candidate_receipts": stored["variant_candidate_receipts"],
        "pack_variants": variants,
        "outcomes": outcomes,
    }
