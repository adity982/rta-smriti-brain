"""Host-owned context compiler authority and safe operator workflows."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any

from . import db
from .agent_profiles import AGENT_PROFILE_SCHEMA_VERSION
from .context_authorization import (
    authorize_task_contract,
    issue_task_contract_capability,
    load_authorized_context,
    register_agent_profile,
    revoke_task_contract_capability,
)
from .context_receipts import (
    audit_context_compilation,
    explain_context_compilation,
    record_context_outcome,
)
from .context_snapshot import run_under_compilation_snapshot
from .runtime_control import is_safe_regular_file, prepare_control_dir
from .task_contracts import TASK_CONTRACT_SCHEMA_VERSION, validate_task_contract

_SECRET_BYTES = 32
_MAX_SECRET_FILE_BYTES = 16 * 1024
_CAPABILITY_TTL_SECONDS = 300
_MAX_CONTEXT_JSON_BYTES = 2 * 1024 * 1024


class _IncompleteAuthorityKey(ValueError):
    """The exclusive creator has published the key path but not its full payload."""


def _database_path(db_path: str | Path) -> Path:
    requested = Path(db_path).expanduser()
    resolved = requested.resolve(strict=True)
    if (
        requested.is_symlink()
        or not resolved.is_file()
        or resolved.is_symlink()
        or resolved.stat().st_nlink != 1
    ):
        raise ValueError("brain database must be an unlinked regular file")
    return resolved


def context_authority_paths(db_path: str | Path) -> dict[str, Path]:
    """Return private authority paths without creating or exposing key material."""
    database = _database_path(db_path)
    identity = os.path.normcase(str(database)) if os.name == "nt" else str(database)
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    directory = database.parent / ".rta-smriti-context"
    return {
        "directory": directory,
        "secret": directory / f"authority-{fingerprint}.secret",
    }


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("context authority key encoding is invalid") from exc


def _windows_protect(value: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    buffer = ctypes.create_string_buffer(value)
    source = DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    protected = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "Rta-Smriti context authority",
        None,
        None,
        None,
        0x1,
        ctypes.byref(protected),
    ):
        raise OSError(
            ctypes.get_last_error(), "Windows DPAPI could not protect authority key"
        )
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        kernel32.LocalFree(protected.pbData)


def _windows_unprotect(value: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    buffer = ctypes.create_string_buffer(value)
    source = DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    clear = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(clear)
    ):
        raise OSError(
            ctypes.get_last_error(), "Windows DPAPI could not read authority key"
        )
    try:
        return ctypes.string_at(clear.pbData, clear.cbData)
    finally:
        kernel32.LocalFree(clear.pbData)


def _encode_secret(value: bytes) -> str:
    if os.name == "nt":
        return f"dpapi-v1:{_b64encode(_windows_protect(value))}"
    return f"owner-file-v1:{_b64encode(value)}"


def _decode_secret(value: str) -> bytes:
    if value.startswith("dpapi-v1:") and os.name == "nt":
        secret = _windows_unprotect(_b64decode(value.removeprefix("dpapi-v1:")))
    elif value.startswith("owner-file-v1:") and os.name != "nt":
        secret = _b64decode(value.removeprefix("owner-file-v1:"))
    else:
        raise ValueError(
            "context authority key protection is incompatible with this host"
        )
    if len(secret) != _SECRET_BYTES:
        raise ValueError("context authority key length is invalid")
    return secret


def _read_secret_file(path: Path) -> bytes:
    if not is_safe_regular_file(path):
        raise ValueError("context authority key is missing or linked")
    before = path.stat()
    if before.st_size > _MAX_SECRET_FILE_BYTES:
        raise ValueError("context authority key file is oversized")
    if os.name != "nt" and (
        before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) & 0o077
    ):
        raise PermissionError("context authority key permissions are not private")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise ValueError("context authority key changed while opening")
        raw = os.read(descriptor, _MAX_SECRET_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_SECRET_FILE_BYTES:
        raise ValueError("context authority key file is oversized")
    if not raw.endswith(b"\n"):
        raise _IncompleteAuthorityKey("context authority key file is incomplete")
    try:
        encoded = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("context authority key encoding is invalid") from exc
    return _decode_secret(encoded)


def _read_secret_file_when_ready(
    path: Path, *, timeout_seconds: float = 2.0
) -> bytes | None:
    """Wait only for an in-progress exclusive creator; reject completed bad files."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if not os.path.lexists(path):
            return None
        try:
            return _read_secret_file(path)
        except _IncompleteAuthorityKey:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
        except ValueError:
            if not os.path.lexists(path):
                return None
            raise


def load_bounded_context_json(
    path: str | Path,
    *,
    maximum_bytes: int = _MAX_CONTEXT_JSON_BYTES,
) -> dict[str, Any]:
    """Read one stable, unlinked JSON object through a bounded descriptor."""
    if (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or not 1 <= maximum_bytes <= _MAX_CONTEXT_JSON_BYTES
    ):
        raise ValueError("context JSON size limit is invalid")
    requested = Path(path).expanduser()
    if not is_safe_regular_file(requested):
        raise ValueError("context JSON must be an unlinked regular file")
    before = requested.stat()
    if before.st_size > maximum_bytes:
        raise ValueError("context JSON exceeds its size limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(requested, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise ValueError("context JSON changed while opening")
        raw = os.read(descriptor, maximum_bytes + 1)
    finally:
        os.close(descriptor)
    if len(raw) > maximum_bytes:
        raise ValueError("context JSON exceeds its size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("context JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise TypeError("context JSON must contain one object")
    return payload


def load_context_authority_secret(db_path: str | Path) -> bytes:
    """Create or read one host-owned key without ever returning it through public status."""
    paths = context_authority_paths(db_path)
    prepare_control_dir(paths["directory"], label="context authority")
    path = paths["secret"]
    encoded: bytes | None = None
    flags = (
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    while True:
        existing = _read_secret_file_when_ready(path)
        if existing is not None:
            return existing
        if encoded is None:
            encoded = f"{_encode_secret(secrets.token_bytes(_SECRET_BYTES))}\n".encode(
                "ascii"
            )
        try:
            descriptor = os.open(path, flags, 0o600)
            break
        except FileExistsError:
            continue
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            path.chmod(0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return _read_secret_file(path)


def context_authority_status(db_path: str | Path) -> dict[str, Any]:
    """Report key readiness using only a non-secret fingerprint."""
    secret = load_context_authority_secret(db_path)
    return {
        "status": "ready",
        "storage": "os_protected" if os.name == "nt" else "owner_file",
        "key_fingerprint": hashlib.sha256(secret).hexdigest()[:16],
    }


def ensure_context_agent_profile(
    conn,
    *,
    project: str,
    profile_id: str,
    actor_id: str,
    max_input_tokens: int,
    privacy_ceiling: str = "internal",
) -> dict[str, Any]:
    """Register an explicit operator-verified consumption profile."""
    profile = {
        "schema_version": AGENT_PROFILE_SCHEMA_VERSION,
        "profile_id": str(profile_id).strip(),
        "source": "operator_declared",
        "verification_status": "verified",
        "input_modalities": ["text"],
        "artifact_forms": ["inline_text", "structured_json"],
        "max_input_tokens": max_input_tokens,
        "reserved_output_tokens": 1_024,
        "host_overhead_tokens": 256,
        "tool_overhead_tokens": 256,
        "tokenizer_family": None,
        "supports": {
            "mcp_resources": True,
            "resource_links": True,
            "file_references": True,
            "structured_json": True,
        },
        "max_item_bytes": 64 * 1024,
        "max_attachment_bytes": 4 * 1024 * 1024,
        "privacy_ceiling": str(privacy_ceiling).strip().casefold(),
        "project_scopes": [str(project).strip()],
        "rendering_conventions": ["plain_text", "structured_json"],
        "unsupported_features": [],
    }
    return register_agent_profile(
        conn,
        project=project,
        profile=profile,
        actor_type="operator",
        actor_id=actor_id,
    )


def build_task_contract(
    *,
    project: str,
    agent_profile_id: str,
    objective: str,
    actor_id: str,
    comparison_modes: list[str] | None = None,
    compiler_mode: str = "balanced",
    max_input_tokens: int = 8_192,
    privacy_ceiling: str = "internal",
) -> dict[str, Any]:
    """Build a conservative single-project contract for operator authorization."""
    created_at = db.now_iso()
    identity = json.dumps(
        {
            "project": str(project).strip(),
            "profile": str(agent_profile_id).strip(),
            "objective": str(objective).strip(),
            "actor": str(actor_id).strip(),
            "created_at": created_at,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    contract = {
        "schema_version": TASK_CONTRACT_SCHEMA_VERSION,
        "contract_id": f"task-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}",
        "project": str(project).strip(),
        "objective": str(objective).strip(),
        "task_type": "context_compilation",
        "risk_class": "routine",
        "acceptance_criteria": [
            "Produce a bounded context pack from authorized project evidence."
        ],
        "required_evidence": [],
        "stop_conditions": [
            "Stop when authorization, repository binding, or evidence integrity is incomplete."
        ],
        "escalation_conditions": [
            "Escalate unresolved contradictions or mandatory evidence omissions."
        ],
        "prohibited_repetition": ["Do not repeat work already verified as complete."],
        "prohibited_actions": [
            "Do not execute tools or mutate project state from context compilation."
        ],
        "scope": {
            "projects": [str(project).strip()],
            "source_types": [],
            "privacy_ceiling": str(privacy_ceiling).strip().casefold(),
            "valid_at": None,
            "recorded_sequence": None,
            "path_globs": [],
        },
        "informational_tool_grants": ["context:compile", "evidence:inspect"],
        "agent_profile_id": str(agent_profile_id).strip(),
        "budgets": {
            "max_input_tokens": max_input_tokens,
            "reserved_output_tokens": 1_024,
            "host_overhead_tokens": 256,
            "tool_overhead_tokens": 256,
            "safety_margin_tokens": 128,
        },
        "compiler_mode": str(compiler_mode).strip().casefold(),
        "comparison_modes": list(comparison_modes or []),
        "created_at": created_at,
        "created_by": {"actor_type": "operator", "actor_id": str(actor_id).strip()},
    }
    return validate_task_contract(contract, authority="operator")


def authorize_context_contract(
    conn,
    *,
    project: str,
    agent_profile_version_id: int,
    contract: dict[str, Any],
    actor_id: str,
) -> dict[str, Any]:
    """Persist a contract only through the explicit operator boundary."""
    return authorize_task_contract(
        conn,
        project=project,
        agent_profile_version_id=agent_profile_version_id,
        contract=contract,
        actor_type="operator",
        actor_id=actor_id,
    )


def _epoch_ms(value: int | None) -> int:
    selected = int(time.time() * 1_000) if value is None else value
    if isinstance(selected, bool) or not isinstance(selected, int) or selected < 0:
        raise ValueError("now_epoch_ms must be a non-negative integer")
    return selected


def _host_capability(
    conn,
    *,
    db_path: str | Path,
    project: str,
    task_contract_id: int,
    principal_type: str,
    principal_id: str,
    session_id: str,
    scopes: list[str],
    now_epoch_ms: int | None,
) -> tuple[dict[str, Any], bytes, int]:
    now = _epoch_ms(now_epoch_ms)
    bucket_ms = max(1_000, (_CAPABILITY_TTL_SECONDS * 1_000) // 2)
    issued_at = now - (now % bucket_ms)
    identity = json.dumps(
        {
            "project": project,
            "task_contract_id": int(task_contract_id),
            "principal_type": principal_type,
            "principal_id": principal_id,
            "session_id": session_id,
            "scopes": sorted(scopes),
            "issued_at_epoch_ms": issued_at,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    secret = load_context_authority_secret(db_path)
    capability = issue_task_contract_capability(
        conn,
        project=project,
        task_contract_id=task_contract_id,
        authority_secret=secret,
        grant_id=f"host-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}",
        principal_type=principal_type,
        principal_id=principal_id,
        session_id=session_id,
        scopes=scopes,
        ttl_seconds=_CAPABILITY_TTL_SECONDS,
        issued_by_id="context-host",
        now_epoch_ms=issued_at,
    )
    return capability, secret, now


def _compilation_contract_id(conn, *, project: str, compilation_id: str) -> int:
    row = conn.execute(
        """
        SELECT c.task_contract_id
        FROM context_compilations c
        JOIN projects p ON p.id = c.project_id
        WHERE p.name = ? AND c.compilation_id = ?
        """,
        (str(project).strip(), str(compilation_id).strip()),
    ).fetchone()
    if row is None:
        raise ValueError("unknown project context compilation")
    return int(row["task_contract_id"])


def _variant_metadata(variant_id: str, pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": variant_id,
        "mode": pack["compiler_mode"],
        "status": pack["status"],
        "pack_digest": pack["context_pack_digest"],
        "used_tokens": int(pack["budget"]["used_tokens"]),
    }


def compile_context_for_agent(
    conn,
    *,
    db_path: str | Path,
    project: str,
    active_root: str | Path,
    task_contract_id: int,
    principal_id: str,
    session_id: str,
    variant_id: str = "primary",
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Compile one authorized pack without exposing bearer or operator-only material."""
    capability, secret, now = _host_capability(
        conn,
        db_path=db_path,
        project=project,
        task_contract_id=task_contract_id,
        principal_type="agent",
        principal_id=principal_id,
        session_id=session_id,
        scopes=["compile:context"],
        now_epoch_ms=now_epoch_ms,
    )
    authorized = load_authorized_context(
        conn,
        project=project,
        task_contract_id=task_contract_id,
        capability_token=capability["capability_token"],
        authority_secret=secret,
        principal_type="agent",
        principal_id=principal_id,
        session_id=session_id,
        required_scope="compile:context",
        now_epoch_ms=now,
    )
    allowed_variants = {
        "primary",
        *(f"mode:{mode}" for mode in authorized["contract"]["comparison_modes"]),
    }
    selected_variant = str(variant_id or "").strip()
    if selected_variant not in allowed_variants:
        raise PermissionError("context variant is not operator authorized")
    compiled = run_under_compilation_snapshot(
        conn,
        project=project,
        active_root=active_root,
        builder=lambda _view, snapshot: {
            "snapshot_digest": snapshot["snapshot_digest"]
        },
        task_contract_id=task_contract_id,
        capability_token=capability["capability_token"],
        authority_secret=secret,
        principal_type="agent",
        principal_id=principal_id,
        session_id=session_id,
        now_epoch_ms=now,
    )
    if compiled.get("status") != "stable":
        return compiled
    variants = compiled["context_variants"]
    if selected_variant not in variants:
        raise RuntimeError("authorized context variant was not compiled")
    return {
        "status": "stable",
        "context_pack": variants[selected_variant],
        "available_variants": [
            _variant_metadata(identifier, variants[identifier])
            for identifier in sorted(variants)
        ],
        "snapshot": {
            "snapshot_digest": compiled["snapshot"]["snapshot_digest"],
            "compiler_version": compiled["snapshot"]["compiler"]["compiler_version"],
        },
        "compilation_receipt": compiled["compilation_receipt"],
    }


def explain_context_for_agent(
    conn,
    *,
    db_path: str | Path,
    project: str,
    compilation_id: str,
    principal_id: str,
    session_id: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Explain a compilation only to its bound agent principal and session."""
    task_contract_id = _compilation_contract_id(
        conn, project=project, compilation_id=compilation_id
    )
    capability, secret, now = _host_capability(
        conn,
        db_path=db_path,
        project=project,
        task_contract_id=task_contract_id,
        principal_type="agent",
        principal_id=principal_id,
        session_id=session_id,
        scopes=["compile:context"],
        now_epoch_ms=now_epoch_ms,
    )
    return explain_context_compilation(
        conn,
        project=project,
        compilation_id=compilation_id,
        capability_token=capability["capability_token"],
        authority_secret=secret,
        principal_type="agent",
        principal_id=principal_id,
        session_id=session_id,
        now_epoch_ms=now,
    )


def audit_context_for_operator(
    conn,
    *,
    db_path: str | Path,
    project: str,
    compilation_id: str,
    operator_id: str,
    session_id: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Return metadata-only receipts to an authenticated local operator."""
    task_contract_id = _compilation_contract_id(
        conn, project=project, compilation_id=compilation_id
    )
    capability, secret, now = _host_capability(
        conn,
        db_path=db_path,
        project=project,
        task_contract_id=task_contract_id,
        principal_type="operator",
        principal_id=operator_id,
        session_id=session_id,
        scopes=["audit:context"],
        now_epoch_ms=now_epoch_ms,
    )
    return audit_context_compilation(
        conn,
        project=project,
        compilation_id=compilation_id,
        capability_token=capability["capability_token"],
        authority_secret=secret,
        principal_type="operator",
        principal_id=operator_id,
        session_id=session_id,
        now_epoch_ms=now,
    )


def record_context_outcome_for_operator(
    conn,
    *,
    db_path: str | Path,
    project: str,
    compilation_id: str,
    operator_id: str,
    session_id: str,
    outcome: dict[str, Any],
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Record an operator-confirmed outcome without exposing its capability."""
    if not isinstance(outcome, dict):
        raise TypeError("context outcome must be an object")
    allowed = {
        "outcome_id",
        "task_status",
        "evidence",
        "acceptance_results",
        "attributions",
        "elapsed_ms",
        "input_tokens",
        "output_tokens",
    }
    unknown = sorted(set(outcome) - allowed)
    if unknown:
        raise ValueError(f"unknown context outcome field: {unknown[0]}")
    task_contract_id = _compilation_contract_id(
        conn, project=project, compilation_id=compilation_id
    )
    capability, secret, now = _host_capability(
        conn,
        db_path=db_path,
        project=project,
        task_contract_id=task_contract_id,
        principal_type="operator",
        principal_id=operator_id,
        session_id=session_id,
        scopes=["confirm:outcome"],
        now_epoch_ms=now_epoch_ms,
    )
    return record_context_outcome(
        conn,
        project=project,
        compilation_id=compilation_id,
        outcome_id=outcome.get("outcome_id"),
        task_status=outcome.get("task_status"),
        attribution_level="operator_confirmed",
        evidence=outcome.get("evidence", {}),
        acceptance_results=outcome.get("acceptance_results", {}),
        actor_type="operator",
        actor_id=operator_id,
        attributions=outcome.get("attributions", []),
        elapsed_ms=outcome.get("elapsed_ms"),
        input_tokens=outcome.get("input_tokens"),
        output_tokens=outcome.get("output_tokens"),
        capability_token=capability["capability_token"],
        authority_secret=secret,
        principal_type="operator",
        principal_id=operator_id,
        session_id=session_id,
        now_epoch_ms=now,
    )


def revoke_context_compilation_grant(
    conn,
    *,
    db_path: str | Path,
    project: str,
    compilation_id: str,
    operator_id: str,
    reason: str,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Revoke the exact bearer grant that produced one compilation receipt."""
    row = conn.execute(
        """
        SELECT g.grant_id
        FROM context_compilations c
        JOIN projects p ON p.id = c.project_id
        JOIN context_authority_grants g ON g.id = c.authority_grant_id
        WHERE p.name = ? AND c.compilation_id = ?
        """,
        (str(project).strip(), str(compilation_id).strip()),
    ).fetchone()
    if row is None:
        raise ValueError("unknown project context compilation")
    revoked = revoke_task_contract_capability(
        conn,
        project=project,
        grant_id=row["grant_id"],
        authority_secret=load_context_authority_secret(db_path),
        revoked_by_id=operator_id,
        reason=reason,
        now_epoch_ms=_epoch_ms(now_epoch_ms),
    )
    return {
        "status": "revoked",
        "compilation_id": str(compilation_id).strip(),
        "revocation_id": revoked["revocation_id"],
        "revoked_at_epoch_ms": revoked["revoked_at_epoch_ms"],
        "idempotent_replay": revoked["idempotent_replay"],
    }
