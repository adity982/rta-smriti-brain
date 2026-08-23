"""Persist and reload operator-authorized context compiler inputs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
from typing import Any

from . import db
from .agent_profiles import (
    agent_profile_digest,
    builtin_agent_profile,
    canonical_agent_profile,
    validate_agent_profile,
)
from .task_contracts import (
    canonical_task_contract,
    task_contract_digest,
    validate_task_contract,
)

_CAPABILITY_VERSION = "rta-smriti.context-capability/v1"
_CAPABILITY_SCOPES = frozenset(
    {"audit:context", "compile:context", "confirm:outcome"}
)
_CAPABILITY_PRINCIPALS = frozenset({"agent", "operator", "system"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _authority_secret(value: Any) -> bytes:
    if not isinstance(value, bytes) or not 32 <= len(value) <= 4_096:
        raise ValueError("authority_secret must contain 32 to 4,096 bytes")
    return value


def _epoch_ms(value: int | None) -> int:
    selected = int(time.time() * 1_000) if value is None else value
    if isinstance(value, bool) or not isinstance(selected, int) or selected < 0:
        raise ValueError("now_epoch_ms must be a non-negative integer")
    return selected


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, TypeError) as exc:
        raise PermissionError("capability token encoding is invalid") from exc


def _sign_capability(claims: dict[str, Any], secret: bytes) -> str:
    payload = _canonical(claims).encode("utf-8")
    encoded = _b64encode(payload)
    signature = _b64encode(
        hmac.new(_authority_secret(secret), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"v1.{encoded}.{signature}"


def _verify_capability_token(token: Any, secret: bytes) -> tuple[dict[str, Any], str]:
    if not isinstance(token, str) or len(token) > 16_384:
        raise PermissionError("capability token is invalid")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise PermissionError("capability token version is invalid")
    expected = _b64encode(
        hmac.new(
            _authority_secret(secret), parts[1].encode("ascii"), hashlib.sha256
        ).digest()
    )
    if not hmac.compare_digest(parts[2], expected):
        raise PermissionError("capability signature is invalid")
    try:
        claims = json.loads(_b64decode(parts[1]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermissionError("capability claims are invalid") from exc
    if not isinstance(claims, dict) or claims.get("schema_version") != _CAPABILITY_VERSION:
        raise PermissionError("capability claims are invalid")
    return claims, hashlib.sha256(token.encode("ascii")).hexdigest()


def _required_text(value: Any, name: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    selected = value.strip()
    if not selected:
        raise ValueError(f"{name} is required")
    if len(selected) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return selected


def _project_row(conn: sqlite3.Connection, project: str) -> sqlite3.Row:
    selected = _required_text(project, "project", maximum=200)
    row = conn.execute(
        "SELECT id, name FROM projects WHERE name = ?",
        (selected,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown project: {selected}")
    return row


def _profile_authority(profile: dict[str, Any]) -> str:
    source = profile["source"]
    if source == "builtin":
        if profile != builtin_agent_profile(profile["profile_id"]):
            raise ValueError("persisted builtin profile does not match the registered builtin")
        return "builtin"
    if source in {"operator_declared", "resolved"}:
        if profile["verification_status"] != "verified":
            raise PermissionError("persisted operator profile is not verified")
        return "operator"
    raise PermissionError("profile source is not authorized for compilation")


def register_agent_profile(
    conn: sqlite3.Connection,
    *,
    project: str,
    profile: dict[str, Any],
    actor_type: str,
    actor_id: str,
) -> dict[str, Any]:
    """Append one immutable profile version under a trusted host authority."""
    if conn.in_transaction:
        raise ValueError("profile registration requires an idle database connection")
    db.init_schema(conn)
    normalized = validate_agent_profile(profile)
    selected_actor = _required_text(actor_type, "actor_type", maximum=32).casefold()
    selected_actor_id = _required_text(actor_id, "actor_id")
    if normalized["source"] in {"operator_declared", "resolved"}:
        if selected_actor != "operator" or normalized["verification_status"] != "verified":
            raise PermissionError("verified profiles require operator authority")
    elif normalized["source"] == "builtin":
        if selected_actor != "system" or normalized != builtin_agent_profile(
            normalized["profile_id"]
        ):
            raise PermissionError("builtin profiles require trusted system authority")
    elif selected_actor not in {"operator", "system"}:
        raise PermissionError("observed profiles require trusted host authority")

    canonical = canonical_agent_profile(normalized)
    digest = agent_profile_digest(normalized)
    created_at = db.now_iso()
    try:
        conn.execute("BEGIN IMMEDIATE")
        project_row = _project_row(conn, project)
        project_id = int(project_row["id"])
        identity = conn.execute(
            "SELECT id FROM agent_profiles WHERE project_id = ? AND profile_id = ?",
            (project_id, normalized["profile_id"]),
        ).fetchone()
        if identity is None:
            agent_profile_id = int(conn.execute(
                """
                INSERT INTO agent_profiles(project_id, profile_id, created_at)
                VALUES (?, ?, ?)
                """,
                (project_id, normalized["profile_id"], created_at),
            ).lastrowid)
        else:
            agent_profile_id = int(identity["id"])
        existing = conn.execute(
            """
            SELECT id, version FROM agent_profile_versions
            WHERE agent_profile_id = ? AND digest = ?
            """,
            (agent_profile_id, digest),
        ).fetchone()
        if existing is None:
            version = int(conn.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM agent_profile_versions WHERE agent_profile_id = ?
                """,
                (agent_profile_id,),
            ).fetchone()[0])
            version_id = int(conn.execute(
                """
                INSERT INTO agent_profile_versions(
                    agent_profile_id, project_id, profile_id, version,
                    schema_version, source, verification_status, canonical_json,
                    digest, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_profile_id,
                    project_id,
                    normalized["profile_id"],
                    version,
                    normalized["schema_version"],
                    normalized["source"],
                    normalized["verification_status"],
                    canonical,
                    digest,
                    created_at,
                    f"{selected_actor}:{selected_actor_id}",
                ),
            ).lastrowid)
        else:
            version_id = int(existing["id"])
            version = int(existing["version"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "agent_profile_id": agent_profile_id,
        "agent_profile_version_id": version_id,
        "profile_id": normalized["profile_id"],
        "version": version,
        "digest": digest,
    }


def authorize_task_contract(
    conn: sqlite3.Connection,
    *,
    project: str,
    agent_profile_version_id: int,
    contract: dict[str, Any],
    actor_type: str,
    actor_id: str,
) -> dict[str, Any]:
    """Persist an immutable task contract after an explicit operator boundary."""
    if conn.in_transaction:
        raise ValueError("contract authorization requires an idle database connection")
    db.init_schema(conn)
    selected_actor = _required_text(actor_type, "actor_type", maximum=32).casefold()
    selected_actor_id = _required_text(actor_id, "actor_id")
    if selected_actor != "operator":
        raise PermissionError("task contract authorization requires an operator")
    normalized = validate_task_contract(contract, authority="operator")
    if normalized["scope"]["projects"] != [normalized["project"]]:
        raise ValueError("v0.8 context compilation requires a single-project contract")
    if normalized["created_by"] != {
        "actor_type": "operator",
        "actor_id": selected_actor_id,
    }:
        raise PermissionError("task contract operator does not match the authorizing actor")
    canonical = canonical_task_contract(normalized, authority="operator")
    digest = task_contract_digest(normalized, authority="operator")
    try:
        conn.execute("BEGIN IMMEDIATE")
        project_row = _project_row(conn, project)
        project_id = int(project_row["id"])
        if normalized["project"] != project_row["name"]:
            raise PermissionError("task contract is not authorized for this project")
        profile_row = conn.execute(
            """
            SELECT v.*, p.retired_at
            FROM agent_profile_versions v
            JOIN agent_profiles p ON p.id = v.agent_profile_id
            WHERE v.id = ? AND v.project_id = ?
            """,
            (int(agent_profile_version_id), project_id),
        ).fetchone()
        if profile_row is None or profile_row["retired_at"] is not None:
            raise PermissionError("agent profile version is not active for this project")
        persisted_profile = validate_agent_profile(json.loads(profile_row["canonical_json"]))
        if (
            canonical_agent_profile(persisted_profile) != profile_row["canonical_json"]
            or agent_profile_digest(persisted_profile) != profile_row["digest"]
        ):
            raise ValueError("persisted agent profile failed its integrity check")
        _profile_authority(persisted_profile)
        if normalized["agent_profile_id"] != profile_row["profile_id"]:
            raise PermissionError("task contract does not match the authorized agent profile")
        existing = conn.execute(
            """
            SELECT id, digest, profile_digest, agent_profile_version_id
            FROM task_contracts
            WHERE project_id = ? AND contract_id = ?
            """,
            (project_id, normalized["contract_id"]),
        ).fetchone()
        if existing is not None:
            if (
                existing["digest"] != digest
                or existing["profile_digest"] != profile_row["digest"]
                or int(existing["agent_profile_version_id"]) != int(agent_profile_version_id)
            ):
                raise ValueError("task contract identity already has different content")
            task_contract_id = int(existing["id"])
        else:
            task_contract_id = int(conn.execute(
                """
                INSERT INTO task_contracts(
                    project_id, agent_profile_version_id, contract_id,
                    schema_version, canonical_json, digest, authorization_state,
                    profile_id, profile_digest, created_at, actor_type, actor_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'operator_authorized', ?, ?, ?,
                          'operator', ?)
                """,
                (
                    project_id,
                    int(agent_profile_version_id),
                    normalized["contract_id"],
                    normalized["schema_version"],
                    canonical,
                    digest,
                    profile_row["profile_id"],
                    profile_row["digest"],
                    normalized["created_at"],
                    selected_actor_id,
                ),
            ).lastrowid)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "task_contract_id": task_contract_id,
        "contract_id": normalized["contract_id"],
        "digest": digest,
        "profile_digest": str(profile_row["digest"]),
        "agent_profile_version_id": int(agent_profile_version_id),
    }


def issue_task_contract_capability(
    conn: sqlite3.Connection,
    *,
    project: str,
    task_contract_id: int,
    authority_secret: bytes,
    grant_id: str,
    principal_type: str,
    principal_id: str,
    session_id: str,
    scopes: list[str],
    ttl_seconds: int,
    issued_by_id: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Issue one short-lived host capability without persisting bearer material."""
    if conn.in_transaction:
        raise ValueError("capability issuance requires an idle database connection")
    db.init_schema(conn)
    secret = _authority_secret(authority_secret)
    selected_grant = _required_text(grant_id, "grant_id", maximum=200)
    selected_principal_type = _required_text(
        principal_type, "principal_type", maximum=32
    ).casefold()
    if selected_principal_type not in _CAPABILITY_PRINCIPALS:
        raise ValueError("principal_type must be agent, operator, or system")
    selected_principal = _required_text(principal_id, "principal_id")
    selected_session = _required_text(session_id, "session_id", maximum=300)
    selected_issuer = _required_text(issued_by_id, "issued_by_id")
    if not isinstance(scopes, list) or not scopes or len(scopes) > 16:
        raise ValueError("scopes must contain between 1 and 16 entries")
    normalized_scopes = sorted(
        {_required_text(scope, "scope", maximum=64).casefold() for scope in scopes}
    )
    if len(normalized_scopes) != len(scopes) or any(
        scope not in _CAPABILITY_SCOPES for scope in normalized_scopes
    ):
        raise ValueError("capability scopes are duplicated or unsupported")
    privileged_scopes = {"audit:context", "confirm:outcome"}
    if privileged_scopes.intersection(normalized_scopes) and selected_principal_type != "operator":
        raise PermissionError("context audit and outcome confirmation require an operator principal")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise TypeError("ttl_seconds must be an integer")
    if not 1 <= ttl_seconds <= 86_400:
        raise ValueError("ttl_seconds must be between 1 and 86,400")
    issued_at = _epoch_ms(now_epoch_ms)
    expires_at = issued_at + ttl_seconds * 1_000
    try:
        conn.execute("BEGIN IMMEDIATE")
        project_row = _project_row(conn, project)
        project_id = int(project_row["id"])
        contract_row = conn.execute(
            """
            SELECT id, project_id, digest, profile_digest, authorization_state, actor_type
            FROM task_contracts WHERE id = ?
            """,
            (int(task_contract_id),),
        ).fetchone()
        if (
            contract_row is None
            or int(contract_row["project_id"]) != project_id
            or contract_row["authorization_state"] != "operator_authorized"
            or contract_row["actor_type"] != "operator"
        ):
            raise PermissionError("capability requires an operator-authorized project contract")
        claims = {
            "schema_version": _CAPABILITY_VERSION,
            "grant_id": selected_grant,
            "project": project_row["name"],
            "project_id": project_id,
            "task_contract_id": int(task_contract_id),
            "contract_digest": contract_row["digest"],
            "profile_digest": contract_row["profile_digest"],
            "principal_type": selected_principal_type,
            "principal_id": selected_principal,
            "session_id": selected_session,
            "scopes": normalized_scopes,
            "issued_at_epoch_ms": issued_at,
            "expires_at_epoch_ms": expires_at,
            "issued_by_id": selected_issuer,
        }
        token = _sign_capability(claims, secret)
        capability_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        existing = conn.execute(
            """
            SELECT * FROM context_authority_grants
            WHERE project_id = ? AND grant_id = ?
            """,
            (project_id, selected_grant),
        ).fetchone()
        if existing is not None:
            if (
                existing["claims_json"] != _canonical(claims)
                or existing["capability_digest"] != capability_digest
            ):
                raise ValueError("grant_id already identifies a different capability")
            authority_grant_id = int(existing["id"])
            idempotent = True
        else:
            authority_grant_id = int(
                conn.execute(
                    """
                    INSERT INTO context_authority_grants(
                        project_id, task_contract_id, grant_id, claims_json,
                        capability_digest, issued_at_epoch_ms, expires_at_epoch_ms,
                        issued_by_type, issued_by_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'operator', ?, ?)
                    """,
                    (
                        project_id,
                        int(task_contract_id),
                        selected_grant,
                        _canonical(claims),
                        capability_digest,
                        issued_at,
                        expires_at,
                        selected_issuer,
                        db.now_iso(),
                    ),
                ).lastrowid
            )
            idempotent = False
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "authority_grant_id": authority_grant_id,
        "grant_id": selected_grant,
        "capability_token": token,
        "capability_digest": capability_digest,
        "expires_at_epoch_ms": expires_at,
        "idempotent_replay": idempotent,
    }


def revoke_task_contract_capability(
    conn: sqlite3.Connection,
    *,
    project: str,
    grant_id: str,
    authority_secret: bytes,
    revoked_by_id: str,
    reason: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Append an irreversible revocation after proving possession of the host key."""
    if conn.in_transaction:
        raise ValueError("capability revocation requires an idle database connection")
    db.init_schema(conn)
    secret = _authority_secret(authority_secret)
    selected_grant = _required_text(grant_id, "grant_id", maximum=200)
    selected_actor = _required_text(revoked_by_id, "revoked_by_id")
    selected_reason = _required_text(reason, "reason", maximum=2_000)
    revoked_at = _epoch_ms(now_epoch_ms)
    try:
        conn.execute("BEGIN IMMEDIATE")
        project_row = _project_row(conn, project)
        row = conn.execute(
            """
            SELECT * FROM context_authority_grants
            WHERE project_id = ? AND grant_id = ?
            """,
            (int(project_row["id"]), selected_grant),
        ).fetchone()
        if row is None:
            raise ValueError("unknown project capability grant")
        claims = json.loads(row["claims_json"])
        token = _sign_capability(claims, secret)
        capability_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        if not hmac.compare_digest(capability_digest, row["capability_digest"]):
            raise PermissionError("capability signature is invalid")
        existing = conn.execute(
            "SELECT * FROM context_authority_revocations WHERE authority_grant_id = ?",
            (int(row["id"]),),
        ).fetchone()
        if existing is not None:
            if (
                existing["reason"] != selected_reason
                or existing["revoked_by_id"] != selected_actor
            ):
                raise ValueError("capability already has a different revocation")
            revocation_id = int(existing["id"])
            idempotent = True
        else:
            revocation_id = int(
                conn.execute(
                    """
                    INSERT INTO context_authority_revocations(
                        authority_grant_id, project_id, task_contract_id,
                        capability_digest, revoked_at_epoch_ms, reason,
                        revoked_by_type, revoked_by_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'operator', ?, ?)
                    """,
                    (
                        int(row["id"]),
                        int(row["project_id"]),
                        int(row["task_contract_id"]),
                        row["capability_digest"],
                        revoked_at,
                        selected_reason,
                        selected_actor,
                        db.now_iso(),
                    ),
                ).lastrowid
            )
            idempotent = False
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "revocation_id": revocation_id,
        "grant_id": selected_grant,
        "revoked_at_epoch_ms": revoked_at,
        "idempotent_replay": idempotent,
    }


def load_authorized_context(
    conn: sqlite3.Connection,
    *,
    project: str,
    task_contract_id: int,
    capability_token: str | None = None,
    authority_secret: bytes | None = None,
    principal_type: str | None = None,
    principal_id: str | None = None,
    session_id: str | None = None,
    required_scope: str | None = None,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Reload and verify authorized compiler inputs from immutable database rows."""
    project_row = _project_row(conn, project)
    project_id = int(project_row["id"])
    row = conn.execute(
        """
        SELECT c.*, v.canonical_json AS profile_json,
               v.digest AS persisted_profile_digest,
               v.profile_id AS persisted_profile_id,
               v.source AS persisted_profile_source,
               v.verification_status AS persisted_profile_verification,
               p.retired_at
        FROM task_contracts c
        JOIN agent_profile_versions v ON v.id = c.agent_profile_version_id
        JOIN agent_profiles p ON p.id = v.agent_profile_id
        WHERE c.id = ?
        """,
        (int(task_contract_id),),
    ).fetchone()
    if row is None or int(row["project_id"]) != project_id:
        raise PermissionError("task contract is not authorized for this project")
    if (
        row["authorization_state"] != "operator_authorized"
        or row["actor_type"] != "operator"
        or row["retired_at"] is not None
    ):
        raise PermissionError("task contract is not currently operator authorized")

    profile = validate_agent_profile(json.loads(row["profile_json"]))
    canonical_profile = canonical_agent_profile(profile)
    profile_digest = agent_profile_digest(profile)
    if (
        canonical_profile != row["profile_json"]
        or profile_digest != row["persisted_profile_digest"]
        or profile_digest != row["profile_digest"]
        or profile["profile_id"] != row["profile_id"]
        or profile["profile_id"] != row["persisted_profile_id"]
        or profile["source"] != row["persisted_profile_source"]
        or profile["verification_status"] != row["persisted_profile_verification"]
    ):
        raise ValueError("persisted agent profile failed its integrity check")
    profile_authority = _profile_authority(profile)

    contract = validate_task_contract(json.loads(row["canonical_json"]), authority="operator")
    canonical_contract = canonical_task_contract(contract, authority="operator")
    contract_digest = task_contract_digest(contract, authority="operator")
    if (
        canonical_contract != row["canonical_json"]
        or contract_digest != row["digest"]
        or contract["contract_id"] != row["contract_id"]
        or contract["project"] != project_row["name"]
        or contract["agent_profile_id"] != profile["profile_id"]
        or contract["authorization"]["state"] != "operator_authorized"
    ):
        raise ValueError("persisted task contract failed its integrity check")
    authority_grant = None
    if any(
        value is not None
        for value in (
            capability_token,
            authority_secret,
            principal_type,
            principal_id,
            session_id,
            required_scope,
        )
    ):
        if any(
            value is None
            for value in (
                capability_token,
                authority_secret,
                principal_type,
                principal_id,
                session_id,
                required_scope,
            )
        ):
            raise PermissionError("complete capability context is required")
        claims, capability_digest = _verify_capability_token(
            capability_token, authority_secret
        )
        grant = conn.execute(
            """
            SELECT g.*, r.id AS revocation_id
            FROM context_authority_grants g
            LEFT JOIN context_authority_revocations r ON r.authority_grant_id = g.id
            WHERE g.project_id = ? AND g.task_contract_id = ?
              AND g.grant_id = ? AND g.capability_digest = ?
            """,
            (
                project_id,
                int(task_contract_id),
                str(claims.get("grant_id") or ""),
                capability_digest,
            ),
        ).fetchone()
        if grant is None or grant["claims_json"] != _canonical(claims):
            raise PermissionError("capability is not authorized for this project contract")
        now = _epoch_ms(now_epoch_ms)
        if now < int(grant["issued_at_epoch_ms"]):
            raise PermissionError("capability is not active yet")
        if now >= int(grant["expires_at_epoch_ms"]):
            raise PermissionError("capability has expired")
        if grant["revocation_id"] is not None:
            raise PermissionError("capability has been revoked")
        expected_bindings = {
            "project": project_row["name"],
            "project_id": project_id,
            "task_contract_id": int(task_contract_id),
            "contract_digest": contract_digest,
            "profile_digest": profile_digest,
            "principal_type": _required_text(
                principal_type, "principal_type", maximum=32
            ).casefold(),
            "principal_id": _required_text(principal_id, "principal_id"),
            "session_id": _required_text(session_id, "session_id", maximum=300),
        }
        for field, expected in expected_bindings.items():
            if claims.get(field) != expected:
                label = "principal" if field in {"principal_type", "principal_id"} else field
                raise PermissionError(f"capability {label} binding does not match")
        selected_scope = _required_text(
            required_scope, "required_scope", maximum=64
        ).casefold()
        if selected_scope not in claims.get("scopes", []):
            raise PermissionError("capability scope is not authorized")
        authority_grant = {
            "authority_grant_id": int(grant["id"]),
            "grant_id": grant["grant_id"],
            "capability_digest": capability_digest,
            "principal_type": claims["principal_type"],
            "principal_id": claims["principal_id"],
            "session_id": claims["session_id"],
            "scopes": list(claims["scopes"]),
            "issued_at_epoch_ms": int(grant["issued_at_epoch_ms"]),
            "expires_at_epoch_ms": int(grant["expires_at_epoch_ms"]),
        }
    return {
        "task_contract_id": int(row["id"]),
        "agent_profile_version_id": int(row["agent_profile_version_id"]),
        "profile": profile,
        "profile_digest": profile_digest,
        "profile_authority": profile_authority,
        "contract": contract,
        "contract_digest": contract_digest,
        "contract_authority": "operator",
        "authority_grant": authority_grant,
    }
