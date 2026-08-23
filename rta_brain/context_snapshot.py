"""Stable compilation snapshots and fail-closed state-fence verification."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterable
from itertools import islice
from pathlib import Path
from typing import Any

from . import __version__, db
from .capture import _verify_event as _verify_capture_event
from .capture import _verify_tombstone as _verify_capture_tombstone
from .context_schema import validate_context_schema_v9
from .repository import (
    canonical_root,
    checkout_identity,
    repository_identity,
    repository_state,
    run_git_inspection,
    same_root,
)
from .temporal import _streaming_projection_digest, _verify_event

MAX_DIRTY_FILE_BYTES = 16 * 1024 * 1024
MAX_DIRTY_TOTAL_BYTES = 128 * 1024 * 1024
MAX_WORKSPACE_MEMBERS = 100
MAX_FENCE_ROWS = 200_000
MAX_FENCE_BYTES = 256 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_ENVELOPE_BYTES = 4 * 1024 * 1024
MAX_BUILDER_RESULT_BYTES = 8 * 1024 * 1024
_REQUIRED_SOURCE_COLUMNS = {
    "projects": {"id", "name", "root_path", "repository_identity", "checkout_identity"},
    "sources": {
        "id", "project_id", "kind", "path", "title", "hash", "metadata_json",
        "created_at", "updated_at",
    },
    "chunks": {"id", "source_id", "ordinal", "text", "hash"},
    "memories": {
        "id", "project_id", "type", "pramana", "text", "confidence", "priority",
        "status", "metadata_json", "created_at", "updated_at",
    },
    "memory_provenance": {
        "memory_id", "source_path", "source_hash", "command", "timestamp",
        "verification_status", "metadata_json",
    },
    "checkpoints": {
        "id", "project_id", "objective", "verified_evidence", "remaining_gaps",
        "next_action", "prohibited_repetition", "source", "trigger", "version", "updated_at",
    },
    "governance_policies": {
        "id", "project_id", "kind", "statement", "effect", "action_contains",
        "path_glob", "required_check", "pramana", "confidence", "provenance_json",
        "overrideable", "expires_at", "status", "retired_reason", "created_at", "retired_at",
    },
    "truth_events": {
        "id", "project_id", "project_sequence", "event_id", "stream_id", "stream_version",
        "event_type", "event_schema", "idempotency_key", "payload_json", "payload_sha256",
        "previous_event_hash", "event_hash", "actor_type", "actor_id", "source",
        "verification_status", "repository_identity", "checkout_identity", "repository_ref",
        "repository_commit", "dirty_digest", "occurred_at", "recorded_at", "privacy_class",
    },
    "truth_claim_versions": {
        "id", "project_id", "claim_id", "subject_key", "subject_display", "predicate",
        "object_json", "polarity", "epistemic_state", "state_reason", "authority_class",
        "confidence", "verification_status", "valid_from", "valid_to",
        "recorded_from_sequence", "recorded_to_sequence", "opened_by_event_id",
        "closed_by_event_id", "repository_anchor_event_id", "provenance_json",
        "revalidate_at", "expires_at", "privacy_class", "sharing_policy", "legacy_memory_id",
    },
    "truth_projection_state": {
        "project_id", "projection_name", "last_event_sequence", "projection_digest",
    },
    "project_root_migrations": {
        "id", "project_id", "previous_root_fingerprint", "new_root_fingerprint",
        "previous_checkout_fingerprint", "new_checkout_fingerprint", "status", "created_at",
    },
    "entities": {"id", "project_id", "type", "name", "canonical_key", "created_at"},
    "edges": {
        "id", "project_id", "from_entity_id", "relation", "to_entity_id", "source_id",
        "memory_id", "confidence", "created_at",
    },
}
_OPTIONAL_SOURCE_COLUMNS = {
    "session_events": {
        "id", "project_id", "session_id", "cursor", "event_type", "payload_json",
        "source", "source_hash", "verification_status", "occurred_at", "recorded_at",
    },
    "work_items": {
        "id", "project_id", "item_type", "external_id", "local_path", "qa_state",
        "decision", "attempt_count", "fallback", "next_action", "metadata_json", "updated_at",
    },
    "capture_events": {
        "id", "project_id", "project_sequence", "event_id", "event_name",
        "external_session_id", "source_id", "recorded_at", "span_id",
        "gap_state", "attributes_json", "event_hash", "previous_event_hash",
    },
    "capture_event_content": {
        "event_row_id", "project_id", "content_json", "content_sha256",
        "content_bytes", "expires_at", "deleted_at", "deletion_reason",
    },
    "capture_tombstones": {
        "id", "project_id", "tombstone_id", "scope", "scope_token",
        "verification_json", "created_at",
    },
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_builder_result(value: Any) -> Any:
    serialized = _canonical_json(value)
    if len(serialized.encode("utf-8")) > MAX_BUILDER_RESULT_BYTES:
        raise ValueError("candidate builder result exceeds the 8 MiB limit")
    return json.loads(serialized)


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    payload = dict(snapshot)
    payload.pop("snapshot_digest", None)
    return _digest(payload)


def _snapshot_shape_is_valid(snapshot: dict[str, Any]) -> bool:
    def exact(value: Any, fields: set[str]) -> bool:
        return isinstance(value, dict) and set(value) == fields

    def row_digest(value: Any) -> bool:
        return (
            exact(value, {"count", "digest"})
            and type(value["count"]) is int
            and value["count"] >= 0
            and digest(value["digest"])
        )

    def digest(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value.lower())
        )

    def text(value: Any, *, nullable: bool = False, maximum: int = 1_000_000) -> bool:
        return (
            nullable and value is None
        ) or (
            isinstance(value, str)
            and len(value.encode("utf-8")) <= maximum
        )

    def bounded_size(value: Any) -> int:
        if isinstance(value, dict):
            return sum(len(str(key).encode("utf-8")) + bounded_size(child) for key, child in value.items())
        if value is None or isinstance(value, (bool, int, float)):
            return len(str(value).encode("ascii"))
        if isinstance(value, str):
            return len(value.encode("utf-8"))
        raise TypeError("snapshot contains an unsupported value type")

    try:
        if not exact(snapshot, {
            "schema_version", "compiler", "project", "git", "fences", "snapshot_digest",
        }):
            return False
        compiler = snapshot["compiler"]
        project = snapshot["project"]
        git = snapshot["git"]
        fences = snapshot["fences"]
        if not exact(compiler, {"compiler_version", "profile_digest", "contract_digest"}):
            return False
        if not exact(project, {
            "id", "name", "root_path", "repository_identity", "checkout_identity",
            "live_repository_identity", "live_checkout_identity", "binding_valid",
            "binding_revision",
        }):
            return False
        if not row_digest(project["binding_revision"]):
            return False
        if not (
            type(project["id"]) is int
            and project["id"] > 0
            and text(project["name"], maximum=200)
            and text(project["root_path"], maximum=32_768)
            and text(project["repository_identity"], nullable=True, maximum=512)
            and text(project["checkout_identity"], nullable=True, maximum=512)
            and text(project["live_repository_identity"], nullable=True, maximum=512)
            and text(project["live_checkout_identity"], nullable=True, maximum=512)
            and type(project["binding_valid"]) is bool
        ):
            return False
        if not exact(git, {
            "is_git_repo", "repository_root", "branch", "head", "dirty_files",
            "dirty_digest", "dirty_manifest_count", "index_digest", "index_entry_count",
        }):
            return False
        if not (
            type(git["is_git_repo"]) is bool
            and text(git["repository_root"], nullable=True, maximum=32_768)
            and text(git["branch"], nullable=True, maximum=1_024)
            and text(git["head"], nullable=True, maximum=128)
            and type(git["dirty_files"]) is int
            and git["dirty_files"] >= 0
            and digest(git["dirty_digest"])
            and type(git["dirty_manifest_count"]) is int
            and git["dirty_manifest_count"] >= 0
            and digest(git["index_digest"])
            and type(git["index_entry_count"]) is int
            and git["index_entry_count"] >= 0
        ):
            return False
        if not exact(fences, {
            "checkpoint", "policy", "truth", "sources", "chunks", "memories",
            "graph", "continuity", "work_state", "capture", "authorization",
        }):
            return False
        checkpoint = fences["checkpoint"]
        if checkpoint is not None and not exact(
            checkpoint, {"id", "version", "updated_at", "digest"},
        ):
            return False
        if checkpoint is not None and not (
            type(checkpoint["id"]) is int
            and checkpoint["id"] > 0
            and type(checkpoint["version"]) is int
            and checkpoint["version"] >= 0
            and text(checkpoint["updated_at"], maximum=128)
            and digest(checkpoint["digest"])
        ):
            return False
        if not all(row_digest(fences[name]) for name in (
            "policy", "sources", "chunks", "memories", "continuity", "work_state",
            "authorization",
        )):
            return False
        capture = fences["capture"]
        if not exact(capture, {"events", "content", "tombstones", "coverage"}):
            return False
        if not all(row_digest(capture[name]) for name in ("events", "content", "tombstones")):
            return False
        capture_coverage = capture["coverage"]
        if not exact(capture_coverage, {
            "total_events", "latest_sequence", "accepted_checkpoint_sequence",
            "uncheckpointed_events", "gap_events", "incomplete_spans",
            "interrupted_sessions", "logically_deleted_scopes",
        }):
            return False
        if not all(
            type(capture_coverage[name]) is int and capture_coverage[name] >= 0
            for name in capture_coverage
        ):
            return False
        if not exact(fences["graph"], {"entities", "edges"}) or not all(
            row_digest(fences["graph"][name]) for name in ("entities", "edges")
        ):
            return False
        truth = fences["truth"]
        if not exact(truth, {
            "events", "projection", "sequence", "event_hash", "projection_digest",
            "projection_state_present",
        }):
            return False
        if not row_digest(truth["events"]) or not row_digest(truth["projection"]):
            return False
        if not (
            type(truth["sequence"]) is int
            and truth["sequence"] >= 0
            and (truth["event_hash"] is None or digest(truth["event_hash"]))
            and digest(truth["projection_digest"])
            and type(truth["projection_state_present"]) is bool
        ):
            return False
        return (
            type(snapshot["schema_version"]) is int
            and text(compiler["compiler_version"], maximum=256)
            and digest(compiler["profile_digest"])
            and digest(compiler["contract_digest"])
            and digest(snapshot["snapshot_digest"])
            and bounded_size(snapshot) <= MAX_SNAPSHOT_ENVELOPE_BYTES
        )
    except (KeyError, TypeError, UnicodeError, ValueError):
        return False


def _rows_digest(rows: Iterable[sqlite3.Row], columns: tuple[str, ...]) -> dict[str, Any]:
    """Digest rows incrementally so the fence does not duplicate large payloads in memory."""
    hasher = hashlib.sha256()
    count = 0
    hasher.update(b"[")
    for row in rows:
        if count:
            hasher.update(b",")
        value = [row[column] for column in columns]
        hasher.update(_canonical_json(value).encode("utf-8"))
        count += 1
    hasher.update(b"]")
    return {"count": count, "digest": hasher.hexdigest()}


class _AggregateBudget:
    __slots__ = ("bytes", "rows")

    def __init__(self) -> None:
        self.rows = 0
        self.bytes = 0

    def consume(self, row: Any, *, label: str) -> None:
        self.rows += 1
        if self.rows > MAX_FENCE_ROWS:
            raise ValueError("snapshot exceeds the aggregate row limit")
        for value in row:
            if isinstance(value, bytes):
                self.bytes += len(value)
            elif value is not None:
                self.bytes += len(str(value).encode("utf-8", errors="replace"))
        if self.bytes > MAX_FENCE_BYTES:
            raise ValueError(f"{label} exceeds the aggregate snapshot byte limit")


def _bounded_rows(
    cursor, *, label: str, budget: _AggregateBudget,
) -> list[sqlite3.Row]:
    rows = []
    for row in cursor:
        budget.consume(row, label=label)
        rows.append(row)
    return rows


def _validate_read_schema(conn: sqlite3.Connection) -> None:
    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        raise ValueError("compilation requires foreign key enforcement")
    if int(conn.execute("PRAGMA recursive_triggers").fetchone()[0]) != 1:
        raise ValueError("compilation requires recursive trigger enforcement")
    if int(conn.execute("PRAGMA trusted_schema").fetchone()[0]) != 0:
        raise ValueError("compilation requires trusted_schema OFF")
    databases = [str(row[1]) for row in conn.execute("PRAGMA database_list")]
    if any(name not in {"main", "temp"} for name in databases):
        raise ValueError("compilation rejects attached databases")
    governed_names = (*_REQUIRED_SOURCE_COLUMNS, *_OPTIONAL_SOURCE_COLUMNS)
    placeholders = ",".join("?" for _ in governed_names)
    shadow = conn.execute(
        f"SELECT name FROM temp.sqlite_master WHERE name IN ({placeholders}) LIMIT 1",
        governed_names,
    ).fetchone()
    if shadow is not None:
        raise ValueError("compilation rejects temporary tables that shadow governed sources")
    for table, required in _REQUIRED_SOURCE_COLUMNS.items():
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA main.table_info({table})")}
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"compilation source schema is missing {table}.{missing[0]}")
    for table, required in _OPTIONAL_SOURCE_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA main.table_info({table})")}
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"compilation source schema is missing {table}.{missing[0]}")
    validate_context_schema_v9(conn)


def _git_paths_from_status(value: str) -> list[tuple[str, str]]:
    fields = value.split("\0")
    paths = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        status = field[:2]
        path = field[3:] if len(field) >= 4 else ""
        if path:
            paths.append((status, path))
        if status and status[0] in {"R", "C"} and index < len(fields):
            replacement = fields[index]
            index += 1
            if replacement:
                paths.append((status, replacement))
    return sorted(set(paths), key=lambda item: (item[1], item[0]))


def _hash_file(
    path: Path, remaining: int, *, allow_missing: bool = False,
) -> tuple[dict[str, Any], int]:
    try:
        stat = path.lstat()
    except OSError as exc:
        if allow_missing:
            return {"state": "deleted"}, remaining
        raise ValueError("dirty file is unavailable for content fencing") from exc
    metadata = {
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "mode": int(stat.st_mode),
    }
    if path.is_symlink():
        try:
            metadata["link_target"] = os.readlink(path)
        except OSError as exc:
            raise ValueError("dirty symlink is unavailable for content fencing") from exc
        return metadata, remaining
    if not path.is_file():
        raise ValueError("dirty path is not a regular file")
    if stat.st_size > MAX_DIRTY_FILE_BYTES or stat.st_size > remaining:
        raise ValueError("dirty file exceeds bounded hash limit")
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            opened_before = os.fstat(handle.fileno())
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                hasher.update(block)
            opened_after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ValueError("dirty file is unavailable for content fencing") from exc
    fingerprint_before = (
        int(opened_before.st_size), int(opened_before.st_mtime_ns), int(opened_before.st_mode),
    )
    fingerprint_after = (
        int(opened_after.st_size), int(opened_after.st_mtime_ns), int(opened_after.st_mode),
    )
    if fingerprint_before != fingerprint_after or fingerprint_before != (
        int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_mode),
    ):
        raise ValueError("dirty file changed while its content fence was captured")
    metadata["content_hash"] = hasher.hexdigest()
    metadata["content_state"] = "hashed"
    return metadata, remaining - int(stat.st_size)


def _git_fence(root: Path, budget: _AggregateBudget) -> dict[str, Any]:
    state = repository_state(root, include_worktree=False)
    if not state.get("is_git_repo"):
        return {
            "is_git_repo": False,
            "repository_root": None,
            "branch": None,
            "head": None,
            "dirty_files": 0,
            "dirty_digest": _digest({"state": "not-a-git-repository"}),
            "dirty_manifest_count": 0,
            "index_digest": _digest({"state": "not-a-git-repository"}),
            "index_entry_count": 0,
        }
    status_result = run_git_inspection(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
        max_output_bytes=MAX_GIT_OUTPUT_BYTES,
    )
    if status_result is None or status_result.returncode != 0:
        raise ValueError("Git status is unavailable for compilation fencing")
    status_text = status_result.stdout
    budget.consume([status_text], label="Git status fence")
    dirty_manifest = []
    remaining = MAX_DIRTY_TOTAL_BYTES
    resolved_root = root.resolve(strict=True)
    for status, relative in _git_paths_from_status(status_text):
        budget.consume([status, relative], label="Git status entry")
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or relative_path.drive
            or ".." in relative_path.parts
        ):
            raise ValueError("Git status path is outside repository root")
        candidate_path = resolved_root.joinpath(*relative_path.parts)
        try:
            candidate_path.resolve(strict=False).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise ValueError("Git status path is outside repository root") from exc
        allow_missing = "D" in status or status[0] in {"R", "C"}
        item, remaining = _hash_file(
            candidate_path, remaining, allow_missing=allow_missing,
        )
        dirty_manifest.append({
            "status": status,
            "path": relative.replace("\\", "/"),
            **item,
        })
    full_head_result = run_git_inspection(
        root, "rev-parse", "HEAD", max_output_bytes=MAX_GIT_OUTPUT_BYTES,
    )
    if full_head_result is None or full_head_result.returncode != 0:
        raise ValueError("Git HEAD is unavailable for compilation fencing")
    full_head = full_head_result.stdout.strip()
    budget.consume([full_head], label="Git HEAD fence")
    index_result = run_git_inspection(
        root, "ls-files", "--stage", "-z", max_output_bytes=MAX_GIT_OUTPUT_BYTES,
    )
    if index_result is None or index_result.returncode != 0:
        raise ValueError("Git index is unavailable for compilation fencing")
    index_text = index_result.stdout
    budget.consume([index_text], label="Git index fence")
    index_entries = [entry for entry in index_text.split("\0") if entry]
    for entry in index_entries:
        budget.consume([entry], label="Git index entry")
    result = {
        "is_git_repo": bool(state.get("is_git_repo")),
        "repository_root": state.get("repository_root"),
        "branch": state.get("branch"),
        "head": full_head,
        "dirty_files": len(dirty_manifest),
        "dirty_digest": _digest({"status": status_text, "files": dirty_manifest}),
        "dirty_manifest_count": len(dirty_manifest),
        "index_digest": _digest(index_text),
        "index_entry_count": len(index_entries),
    }
    return result


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def _capture_fences(
    conn: sqlite3.Connection, project_id: int, budget: _AggregateBudget,
) -> dict[str, Any]:
    checkpoint = conn.execute(
        """
        SELECT c.id, c.version, c.updated_at, c.objective, c.verified_evidence,
               c.remaining_gaps, c.next_action, c.prohibited_repetition,
               c.source, c.trigger, f.fence_sequence
        FROM checkpoints c
        LEFT JOIN checkpoint_capture_fences f ON f.checkpoint_id = c.id
        WHERE c.project_id = ?
        ORDER BY version DESC, updated_at DESC, id DESC LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if checkpoint is not None:
        budget.consume(checkpoint, label="checkpoint fence")
    checkpoint_value = None if checkpoint is None else {
        "id": int(checkpoint["id"]),
        "version": int(checkpoint["version"]),
        "updated_at": checkpoint["updated_at"],
        "digest": _digest([
            checkpoint[column] for column in checkpoint.keys()  # noqa: SIM118
        ]),
    }
    policies = _bounded_rows(conn.execute(
        """
        SELECT id, kind, statement, effect, action_contains, path_glob,
               required_check, pramana, confidence, provenance_json,
               overrideable, expires_at, status, retired_reason,
               created_at, retired_at
        FROM governance_policies WHERE project_id = ? ORDER BY id
        """,
        (project_id,),
    ), label="policy fence", budget=budget)
    truth_events = _bounded_rows(conn.execute(
        """
        SELECT *
        FROM truth_events WHERE project_id = ? ORDER BY project_sequence
        """,
        (project_id,),
    ), label="truth-event fence", budget=budget)
    previous_hash = None
    for expected_sequence, event in enumerate(truth_events, start=1):
        _verify_event(event, sequence=expected_sequence, previous_hash=previous_hash)
        previous_hash = str(event["event_hash"])
    live_projection_digest = _streaming_projection_digest(
        conn,
        project_id,
        row_observer=lambda row, table: budget.consume(
            row, label=f"{table} projection fence",
        ),
    )
    projection_state = conn.execute(
        """
        SELECT last_event_sequence, projection_digest FROM truth_projection_state
        WHERE project_id = ? AND projection_name = 'claims'
        """,
        (project_id,),
    ).fetchone()
    if projection_state is not None and (
        int(projection_state["last_event_sequence"])
        != (int(truth_events[-1]["project_sequence"]) if truth_events else 0)
        or str(projection_state["projection_digest"]) != live_projection_digest
    ):
        raise ValueError("truth projection state does not match the event ledger")
    truth_projection = _bounded_rows(conn.execute(
        """
        SELECT claim_id, subject_key, predicate, object_json, polarity,
               epistemic_state, authority_class, confidence, verification_status,
               valid_from, valid_to, recorded_from_sequence, recorded_to_sequence,
               opened_by_event_id, closed_by_event_id, privacy_class, sharing_policy
        FROM truth_claim_versions WHERE project_id = ?
        ORDER BY claim_id, recorded_from_sequence, id
        """,
        (project_id,),
    ), label="truth-projection fence", budget=budget)
    sources = _bounded_rows(conn.execute(
        """
        SELECT id, kind, path, title, hash, metadata_json, created_at, updated_at
        FROM sources WHERE project_id = ? ORDER BY id
        """,
        (project_id,),
    ), label="source fence", budget=budget)
    chunks = _bounded_rows(conn.execute(
        """
        SELECT c.id, c.source_id, c.ordinal, c.text, c.hash
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE s.project_id = ? ORDER BY c.source_id, c.ordinal, c.id
        """,
        (project_id,),
    ), label="chunk fence", budget=budget)
    memories = _bounded_rows(conn.execute(
        """
        SELECT m.id, m.type, m.pramana, m.text, m.confidence, m.priority,
               m.status, m.metadata_json, m.created_at, m.updated_at,
               mp.source_path, mp.source_hash, mp.command,
               mp.timestamp AS provenance_timestamp,
               mp.verification_status AS provenance_verification_status,
               mp.metadata_json AS provenance_metadata_json
        FROM memories m LEFT JOIN memory_provenance mp ON mp.memory_id = m.id
        WHERE m.project_id = ? ORDER BY m.id
        """,
        (project_id,),
    ), label="memory fence", budget=budget)
    entities = _bounded_rows(conn.execute(
        """
        SELECT id, type, name, canonical_key, created_at
        FROM entities WHERE project_id = ? ORDER BY id
        """,
        (project_id,),
    ), label="entity fence", budget=budget)
    edges = _bounded_rows(conn.execute(
        """
        SELECT id, from_entity_id, relation, to_entity_id, source_id, memory_id,
               confidence, created_at
        FROM edges WHERE project_id = ? ORDER BY id
        """,
        (project_id,),
    ), label="edge fence", budget=budget)
    continuity = []
    if _table_exists(conn, "session_events"):
        continuity = _bounded_rows(conn.execute(
            """
            SELECT id, session_id, cursor, event_type, payload_json, source,
                   source_hash, verification_status, occurred_at, recorded_at
            FROM session_events WHERE project_id = ? ORDER BY id
            """,
            (project_id,),
        ), label="continuity fence", budget=budget)
    work_state = []
    if _table_exists(conn, "work_items"):
        work_state = _bounded_rows(conn.execute(
            """
            SELECT id, item_type, external_id, local_path, qa_state, decision,
                   attempt_count, fallback, next_action, metadata_json, updated_at
            FROM work_items WHERE project_id = ? ORDER BY item_type, external_id, id
            """,
            (project_id,),
        ), label="work-state fence", budget=budget)
    capture_events = []
    capture_event_content = []
    capture_tombstones = []
    if _table_exists(conn, "capture_events"):
        capture_events = _bounded_rows(conn.execute(
            """
            SELECT * FROM capture_events
            WHERE project_id = ? ORDER BY project_sequence
            """,
            (project_id,),
        ), label="capture-event fence", budget=budget)
        if _table_exists(conn, "capture_event_content"):
            capture_event_content = _bounded_rows(conn.execute(
                """
                SELECT event_row_id, project_id, content_json, content_sha256,
                       content_bytes, expires_at, deleted_at, deletion_reason
                FROM capture_event_content
                WHERE project_id = ? ORDER BY event_row_id
                """,
                (project_id,),
            ), label="capture-content fence", budget=budget)
        content_by_event = {
            int(row["event_row_id"]): row for row in capture_event_content
        }
        previous_capture_hash = None
        for sequence, event in enumerate(capture_events, start=1):
            content = content_by_event.get(int(event["id"]))
            integrity_row = dict(event)
            integrity_row.update({
                "content_json": None if content is None else content["content_json"],
                "content_sha256": None if content is None else content["content_sha256"],
                "content_deleted_at": None if content is None else content["deleted_at"],
            })
            _verify_capture_event(
                integrity_row,
                sequence=sequence,
                previous_hash=previous_capture_hash,
            )
            previous_capture_hash = str(event["event_hash"])
    if _table_exists(conn, "capture_tombstones"):
        capture_tombstones = _bounded_rows(conn.execute(
            """
            SELECT * FROM capture_tombstones
            WHERE project_id = ? ORDER BY id
            """,
            (project_id,),
        ), label="capture-tombstone fence", budget=budget)
        for tombstone in capture_tombstones:
            _verify_capture_tombstone(tombstone)

    accepted_checkpoint_sequence = 0
    if checkpoint is not None:
        if checkpoint["fence_sequence"] is not None:
            accepted_checkpoint_sequence = int(checkpoint["fence_sequence"])
        else:
            accepted_checkpoint_sequence = max(
                [
                    0,
                    *(
                        int(event["project_sequence"])
                        for event in capture_events
                        if str(event["recorded_at"]) < str(checkpoint["updated_at"])
                    ),
                ]
            )
    capture_window = [
        event for event in capture_events
        if int(event["project_sequence"]) > accepted_checkpoint_sequence
    ]
    session_state: dict[tuple[str, str], bool] = {}
    incomplete_spans: set[tuple[str, str, str]] = set()
    gap_events = 0
    for event in capture_window:
        key = (str(event["source_id"]), str(event["external_session_id"]))
        name = str(event["event_name"])
        interrupted = session_state.get(key, False)
        if name == "turn.interrupted.v1":
            interrupted = True
        elif name in {"turn.completed.v1", "session.ended.v1"}:
            interrupted = False
        session_state[key] = interrupted
        if name == "capture.gap.v1" or event["gap_state"] == "detected":
            gap_events += 1
        span = event["span_id"]
        if span and name.endswith(".started.v1"):
            incomplete_spans.add((*key, str(span)))
        elif span and name.endswith((".completed.v1", ".failed.v1")):
            incomplete_spans.discard((*key, str(span)))
    authorization = _bounded_rows(conn.execute(
        """
        SELECT 'profile' AS record_type, p.id AS record_id, p.profile_id AS key,
               p.created_at AS created_at, p.retired_at AS mutable_state,
               NULL AS digest, NULL AS authorization_state,
               NULL AS actor_type, NULL AS actor_id
        FROM agent_profiles p
        WHERE p.project_id = ?
        UNION ALL
        SELECT 'profile_version', v.id, v.profile_id, v.created_at, NULL,
               v.digest, v.verification_status, v.source, v.created_by
        FROM agent_profile_versions v
        WHERE v.project_id = ?
        UNION ALL
        SELECT 'task_contract', c.id, c.contract_id, c.created_at, NULL,
               c.digest, c.authorization_state, c.actor_type, c.actor_id
        FROM task_contracts c
        WHERE c.project_id = ?
        UNION ALL
        SELECT 'authority_grant', g.id, g.grant_id, g.created_at,
               CAST(g.expires_at_epoch_ms AS TEXT), g.capability_digest,
               'issued', 'operator', g.issued_by_id
        FROM context_authority_grants g
        WHERE g.project_id = ?
        UNION ALL
        SELECT 'authority_revocation', r.id, g.grant_id, r.created_at,
               CAST(r.revoked_at_epoch_ms AS TEXT), r.capability_digest,
               'revoked', 'operator', r.revoked_by_id
        FROM context_authority_revocations r
        JOIN context_authority_grants g ON g.id = r.authority_grant_id
        WHERE r.project_id = ?
        ORDER BY record_type, record_id
        """,
        (project_id, project_id, project_id, project_id, project_id),
    ), label="authorization fence", budget=budget)
    return {
        "checkpoint": checkpoint_value,
        "policy": _rows_digest(policies, tuple(policies[0].keys()) if policies else ("id",)),
        "truth": {
            "events": _rows_digest(
                truth_events, tuple(truth_events[0].keys()) if truth_events else ("project_sequence",),
            ),
            "projection": _rows_digest(
                truth_projection, tuple(truth_projection[0].keys()) if truth_projection else ("claim_id",),
            ),
            "sequence": int(truth_events[-1]["project_sequence"]) if truth_events else 0,
            "event_hash": truth_events[-1]["event_hash"] if truth_events else None,
            "projection_digest": live_projection_digest,
            "projection_state_present": projection_state is not None,
        },
        "sources": _rows_digest(sources, tuple(sources[0].keys()) if sources else ("id",)),
        "chunks": _rows_digest(chunks, tuple(chunks[0].keys()) if chunks else ("id",)),
        "memories": _rows_digest(
            memories, tuple(memories[0].keys()) if memories else ("id",),
        ),
        "graph": {
            "entities": _rows_digest(
                entities, tuple(entities[0].keys()) if entities else ("id",),
            ),
            "edges": _rows_digest(edges, tuple(edges[0].keys()) if edges else ("id",)),
        },
        "continuity": _rows_digest(
            continuity, tuple(continuity[0].keys()) if continuity else ("id",),
        ),
        "work_state": _rows_digest(
            work_state, tuple(work_state[0].keys()) if work_state else ("id",),
        ),
        "capture": {
            "events": _rows_digest(
                capture_events,
                tuple(capture_events[0].keys()) if capture_events else ("id",),
            ),
            "content": _rows_digest(
                capture_event_content,
                tuple(capture_event_content[0].keys())
                if capture_event_content else ("event_row_id",),
            ),
            "tombstones": _rows_digest(
                capture_tombstones,
                tuple(capture_tombstones[0].keys()) if capture_tombstones else ("id",),
            ),
            "coverage": {
                "total_events": len(capture_events),
                "latest_sequence": (
                    int(capture_events[-1]["project_sequence"])
                    if capture_events else 0
                ),
                "accepted_checkpoint_sequence": accepted_checkpoint_sequence,
                "uncheckpointed_events": len(capture_window),
                "gap_events": gap_events,
                "incomplete_spans": len(incomplete_spans),
                "interrupted_sessions": sum(session_state.values()),
                "logically_deleted_scopes": len(capture_tombstones),
            },
        },
        "authorization": _rows_digest(
            authorization,
            tuple(authorization[0].keys()) if authorization else ("record_type",),
        ),
    }


def _capture_compilation_snapshot(
    conn: sqlite3.Connection, *, project: str, active_root: str | Path,
    strict_binding: bool, compiler_version: str,
    profile_digest: str | None, contract_digest: str | None,
) -> dict[str, Any]:
    schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if schema_version != db.SCHEMA_VERSION:
        raise ValueError(
            f"compilation requires schema {db.SCHEMA_VERSION}; database uses {schema_version}"
        )
    _validate_read_schema(conn)
    budget = _AggregateBudget()
    row = conn.execute(
        """
        SELECT id, name, root_path, repository_identity, checkout_identity
        FROM projects WHERE name = ?
        """,
        (str(project).strip(),),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown project: {project}")
    budget.consume(row, label="project binding")
    requested_root = canonical_root(active_root)
    if strict_binding and (
        not row["root_path"] or not same_root(row["root_path"], requested_root)
    ):
        raise ValueError("compilation requires the exact canonical project root")
    try:
        live_repository = repository_identity(requested_root, create_marker=False)
        live_checkout = checkout_identity(requested_root, create_marker=False)
    except (OSError, ValueError):
        live_repository = None
        live_checkout = None
    binding_valid = (
        bool(row["root_path"])
        and same_root(row["root_path"], requested_root)
        and row["repository_identity"] == live_repository
        and row["checkout_identity"] == live_checkout
    )
    if strict_binding and not binding_valid:
        raise ValueError("compilation rejected because the canonical binding drifted")
    binding_rows = _bounded_rows(conn.execute(
        """
        SELECT id, previous_root_fingerprint, new_root_fingerprint,
               previous_checkout_fingerprint, new_checkout_fingerprint,
               status, created_at
        FROM project_root_migrations WHERE project_id = ? ORDER BY id
        """,
        (int(row["id"]),),
    ), label="binding fence", budget=budget)
    project_value = {
        "id": int(row["id"]),
        "name": row["name"],
        "root_path": row["root_path"],
        "repository_identity": row["repository_identity"],
        "checkout_identity": row["checkout_identity"],
        "live_repository_identity": live_repository,
        "live_checkout_identity": live_checkout,
        "binding_valid": binding_valid,
        "binding_revision": _rows_digest(
            binding_rows,
            tuple(binding_rows[0].keys()) if binding_rows else ("id",),
        ),
    }
    compiler_version = str(compiler_version or "").strip()
    if not compiler_version or len(compiler_version) > 256:
        raise ValueError("compiler_version is required and must be at most 256 characters")
    for name, value in (
        ("profile_digest", profile_digest), ("contract_digest", contract_digest),
    ):
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value.lower())
        ):
            raise ValueError(f"{name} must be a SHA-256 digest or null")
    compiler_value = {
        "compiler_version": compiler_version,
        "profile_digest": profile_digest.lower() if profile_digest is not None else None,
        "contract_digest": contract_digest.lower() if contract_digest is not None else None,
    }
    payload = {
        "schema_version": schema_version,
        "compiler": compiler_value,
        "project": project_value,
        "git": _git_fence(Path(requested_root), budget),
        "fences": _capture_fences(conn, int(row["id"]), budget),
    }
    payload["snapshot_digest"] = _snapshot_digest(payload)
    return payload


def capture_compilation_snapshot(
    conn: sqlite3.Connection, *, project: str, active_root: str | Path,
    compiler_version: str = __version__, profile_digest: str | None = None,
    contract_digest: str | None = None,
) -> dict[str, Any]:
    """Capture all compiler-critical state under one SQLite read transaction."""
    if conn.in_transaction:
        raise ValueError("compilation requires an idle database connection")
    if profile_digest is None or contract_digest is None:
        raise ValueError("compilation requires profile_digest and contract_digest")
    conn.execute("BEGIN")
    try:
        snapshot = _capture_compilation_snapshot(
            conn, project=project, active_root=active_root, strict_binding=True,
            compiler_version=compiler_version, profile_digest=profile_digest,
            contract_digest=contract_digest,
        )
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    conn.commit()
    return snapshot


def _changed_fences(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changed = []
    if before["schema_version"] != after["schema_version"]:
        changed.append("schema")
    if before.get("compiler") != after.get("compiler"):
        changed.append("compiler_binding")
    before_project = before["project"]
    after_project = after["project"]
    binding_fields = (
        "id", "name", "root_path", "repository_identity", "checkout_identity",
        "live_repository_identity", "live_checkout_identity", "binding_valid",
        "binding_revision",
    )
    if any(before_project.get(key) != after_project.get(key) for key in binding_fields):
        changed.append("binding")
    if before["git"] != after["git"]:
        changed.append("git")
    fence_names = sorted(set(before["fences"]) | set(after["fences"]))
    for name in fence_names:
        if before["fences"].get(name) != after["fences"].get(name):
            changed.append(name)
    return changed


def _verify_snapshot_fences_in_transaction(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    active_root: str | Path,
) -> dict[str, Any]:
    compiler = snapshot.get("compiler") or {}
    current = _capture_compilation_snapshot(
        conn,
        project=str(snapshot["project"]["name"]),
        active_root=active_root,
        strict_binding=False,
        compiler_version=compiler.get("compiler_version"),
        profile_digest=compiler.get("profile_digest"),
        contract_digest=compiler.get("contract_digest"),
    )
    changed = _changed_fences(snapshot, current)
    if changed:
        return {
            "status": "state_changed_retry",
            "changed": changed,
            "previous_snapshot_digest": snapshot.get("snapshot_digest"),
            "current_snapshot_digest": current["snapshot_digest"],
        }
    return {
        "status": "stable",
        "changed": [],
        "snapshot_digest": snapshot["snapshot_digest"],
    }


def verify_compilation_snapshot(
    conn: sqlite3.Connection, snapshot: dict[str, Any], *, active_root: str | Path,
    expected_compiler_version: str | None = None,
    expected_profile_digest: str | None = None,
    expected_contract_digest: str | None = None,
) -> dict[str, Any]:
    """Re-read the fence and refuse emission if any compiler input changed."""
    if not isinstance(snapshot, dict) or "project" not in snapshot:
        raise ValueError("snapshot is invalid")
    try:
        supplied_digest = snapshot.get("snapshot_digest")
        if supplied_digest != _snapshot_digest(snapshot):
            return {
                "status": "state_changed_retry",
                "changed": ["snapshot_integrity"],
            }
    except (TypeError, ValueError):
        return {
            "status": "state_changed_retry",
            "changed": ["snapshot_integrity"],
        }
    if not _snapshot_shape_is_valid(snapshot):
        return {
            "status": "state_changed_retry",
            "changed": ["snapshot_integrity"],
        }
    if conn.in_transaction:
        raise ValueError("compilation requires an idle database connection")
    actual_compiler = snapshot.get("compiler") or {}
    if any(value is None for value in (
        expected_compiler_version, expected_profile_digest, expected_contract_digest,
    )):
        return {
            "status": "state_changed_retry",
            "changed": ["compiler_binding"],
        }
    expected_compiler = {
        "compiler_version": str(expected_compiler_version).strip(),
        "profile_digest": (
            expected_profile_digest.lower() if expected_profile_digest is not None else None
        ),
        "contract_digest": (
            expected_contract_digest.lower() if expected_contract_digest is not None else None
        ),
    }
    if (
        any(value is not None for value in expected_compiler.values())
        and any(
            expected is not None and actual_compiler.get(name) != expected
            for name, expected in expected_compiler.items()
        )
    ):
        return {
            "status": "state_changed_retry",
            "changed": ["compiler_binding"],
        }
    conn.execute("BEGIN")
    try:
        result = _verify_snapshot_fences_in_transaction(
            conn,
            snapshot,
            active_root=active_root,
        )
    except BaseException as exc:
        if conn.in_transaction:
            conn.rollback()
        if isinstance(exc, Exception):
            return {"status": "state_changed_retry", "changed": ["snapshot_unavailable"]}
        raise
    conn.commit()
    return result


class _ReadOnlyCompilationView:
    """Expose only detached candidates for the selected project."""

    __slots__ = ("__candidate_payload",)

    def __init__(self, candidate_payload: dict[str, Any]) -> None:
        self.__candidate_payload = _canonical_json(candidate_payload)

    def context_candidates(self) -> dict[str, Any]:
        return json.loads(self.__candidate_payload)

    def context_pack(self) -> dict[str, Any]:
        return json.loads(self.__candidate_payload)


def _open_read_only_compilation_connection(
    connection: sqlite3.Connection,
) -> sqlite3.Connection:
    main_path = next(
        (
            str(row[2])
            for row in connection.execute("PRAGMA database_list")
            if str(row[1]) == "main"
        ),
        "",
    )
    if not main_path:
        raise ValueError("compilation requires a file-backed brain database")
    path = Path(main_path).resolve(strict=True)
    reader = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        reader.row_factory = sqlite3.Row
        reader.execute("PRAGMA busy_timeout = 5000")
        reader.execute("PRAGMA foreign_keys = ON")
        reader.execute("PRAGMA recursive_triggers = ON")
        reader.execute("PRAGMA trusted_schema = OFF")
        reader.execute("PRAGMA query_only = ON")
        return reader
    except BaseException:
        reader.close()
        raise


def run_under_compilation_snapshot(
    conn: sqlite3.Connection,
    *,
    project: str,
    active_root: str | Path,
    builder: Callable[[Any, dict[str, Any]], Any],
    compiler_version: str = __version__,
    task_contract_id: int | None = None,
    capability_token: str | None = None,
    authority_secret: bytes | None = None,
    principal_type: str | None = None,
    principal_id: str | None = None,
    session_id: str | None = None,
    now_epoch_ms: int | None = None,
) -> dict[str, Any]:
    """Build from one read snapshot and expose a result only after fence verification."""
    if conn.in_transaction:
        raise ValueError("compilation requires an idle database connection")
    if task_contract_id is None:
        raise ValueError("compilation requires task_contract_id")
    compiler_version = str(compiler_version or "").strip()
    reader = _open_read_only_compilation_connection(conn)
    try:
        reader.execute("BEGIN")
        from .context_authorization import load_authorized_context

        try:
            authorization = load_authorized_context(
                reader,
                project=project,
                task_contract_id=task_contract_id,
                capability_token=capability_token,
                authority_secret=authority_secret,
                principal_type=principal_type,
                principal_id=principal_id,
                session_id=session_id,
                required_scope="compile:context",
                now_epoch_ms=now_epoch_ms,
            )
        except PermissionError:
            reader.rollback()
            reader.close()
            return {
                "status": "authorization_required",
                "reason": "persisted operator authorization is required",
            }
        profile = authorization["profile"]
        contract = authorization["contract"]
        profile_digest = authorization["profile_digest"]
        contract_digest = authorization["contract_digest"]
        authority_grant = authorization["authority_grant"]
        if authority_grant is None:
            raise PermissionError("persisted host capability is required")
        snapshot = _capture_compilation_snapshot(
            reader, project=project, active_root=active_root, strict_binding=True,
            compiler_version=compiler_version, profile_digest=profile_digest,
            contract_digest=contract_digest,
        )
        from .context_candidates import (
            CandidateAuthority,
            adapt_context_candidates,
        )
        from .context_selection import (
            build_consumer_context_pack,
            select_context_candidates,
        )

        adapted = adapt_context_candidates(
            reader,
            project=project,
            valid_at=contract["scope"]["valid_at"],
            recorded_sequence=contract["scope"]["recorded_sequence"],
        )
        candidate_authority = CandidateAuthority(_digest({
            "snapshot_digest": snapshot["snapshot_digest"],
            "compiler_version": compiler_version,
            "profile_digest": profile_digest,
            "contract_digest": contract_digest,
        }))
        candidate_authority.issue(adapted["candidates"])
        selection = select_context_candidates(
            adapted["candidates"], contract=contract, profile=profile,
            authority=authorization["contract_authority"],
            profile_authority=authorization["profile_authority"],
            candidate_authority=candidate_authority,
            snapshot_digest=snapshot["snapshot_digest"],
            compiler_version=compiler_version,
        )
        candidate_payload = build_consumer_context_pack(selection)
        alternative_variants = []
        context_variants = {"primary": candidate_payload}
        variant_audits = {}
        for mode in contract.get("comparison_modes", []):
            alternative_selection = select_context_candidates(
                adapted["candidates"], contract=contract, profile=profile,
                authority=authorization["contract_authority"],
                profile_authority=authorization["profile_authority"],
                candidate_authority=candidate_authority,
                snapshot_digest=snapshot["snapshot_digest"],
                compiler_version=compiler_version,
                compiler_mode_override=mode,
            )
            alternative_pack = build_consumer_context_pack(alternative_selection)
            variant_id = f"mode:{mode}"
            alternative_variants.append({
                "variant_id": variant_id,
                "selection": alternative_selection,
                "consumer_pack": alternative_pack,
            })
            context_variants[variant_id] = alternative_pack
            variant_audits[variant_id] = alternative_selection
        builder_snapshot = json.loads(_canonical_json({
            "schema_version": snapshot["schema_version"],
            "snapshot_digest": snapshot["snapshot_digest"],
            "compiler": snapshot["compiler"],
            "project": {
                "id": snapshot["project"]["id"],
                "name": snapshot["project"]["name"],
                "binding_valid": snapshot["project"]["binding_valid"],
            },
        }))
        reader.commit()
    except BaseException as exc:
        if reader.in_transaction:
            reader.rollback()
        if isinstance(exc, Exception):
            return {"status": "failed", "error": "candidate_builder_failed"}
        raise
    finally:
        reader.close()
    try:
        result = _bounded_builder_result(
            builder(_ReadOnlyCompilationView(candidate_payload), builder_snapshot)
        )
    except BaseException as exc:
        if isinstance(exc, Exception):
            return {"status": "failed", "error": "candidate_builder_failed"}
        raise
    from .context_receipts import CompilationStateChanged, persist_compilation_receipt

    try:
        compilation_receipt = persist_compilation_receipt(
            conn,
            project=project,
            task_contract_id=task_contract_id,
            selection=selection,
            consumer_pack=candidate_payload,
            authority_grant=authority_grant,
            alternative_variants=alternative_variants,
            precommit_verifier=lambda locked: _verify_snapshot_fences_in_transaction(
                locked,
                snapshot,
                active_root=active_root,
            ),
        )
    except CompilationStateChanged as exc:
        return exc.result
    return {
        "status": "stable",
        "snapshot": snapshot,
        "result": result,
        "operator_audit": selection,
        "variant_audits": variant_audits,
        "context_variants": context_variants,
        "compilation_receipt": compilation_receipt,
    }


def inspect_workspace_members_read_only(
    members: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Inspect external brain schemas without migrating or writing member databases."""
    selected = list(islice(iter(members), MAX_WORKSPACE_MEMBERS + 1))
    if len(selected) > MAX_WORKSPACE_MEMBERS:
        raise ValueError(f"workspace exceeds {MAX_WORKSPACE_MEMBERS} members")
    results = []
    for item in selected:
        member = {
            "project": "",
            "read_only": True,
            "eligible": False,
        }
        try:
            if not isinstance(item, dict):
                raise TypeError("workspace member descriptor must be an object")
            project = str(item.get("project") or "").strip()
            path_value = item.get("db_path")
            member["project"] = project
            requested = Path(path_value).expanduser()
            if requested.is_symlink():
                raise ValueError("linked member databases are not accepted")
            path = requested.resolve(strict=True)
            if not path.is_file() or path.stat().st_nlink > 1:
                raise ValueError("member database must be one regular unlinked file")
            member_conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            try:
                member_conn.row_factory = sqlite3.Row
                member_conn.execute("PRAGMA foreign_keys = ON")
                member_conn.execute("PRAGMA recursive_triggers = ON")
                member_conn.execute("PRAGMA trusted_schema = OFF")
                member_conn.execute("PRAGMA query_only = ON")
                member_conn.execute("BEGIN")
                schema_version = int(member_conn.execute("PRAGMA user_version").fetchone()[0])
                member["schema_version"] = schema_version
                if schema_version != db.SCHEMA_VERSION:
                    member["status"] = "isolated_schema_mismatch"
                else:
                    try:
                        _validate_read_schema(member_conn)
                    except (sqlite3.Error, TypeError, ValueError):
                        member["status"] = "isolated_schema_mismatch"
                    else:
                        project_row = member_conn.execute(
                            """
                            SELECT root_path, repository_identity, checkout_identity
                            FROM projects WHERE name = ?
                            """,
                            (project,),
                        ).fetchone()
                        if project_row is None:
                            member["status"] = "isolated_project_missing"
                        else:
                            try:
                                root = canonical_root(project_row["root_path"])
                                live_repository = repository_identity(root, create_marker=False)
                                live_checkout = checkout_identity(root, create_marker=False)
                            except (OSError, TypeError, ValueError):
                                member["status"] = "isolated_binding_mismatch"
                            else:
                                if (
                                    project_row["repository_identity"] != live_repository
                                    or project_row["checkout_identity"] != live_checkout
                                ):
                                    member["status"] = "isolated_binding_mismatch"
                                else:
                                    member["status"] = "eligible"
                                    member["eligible"] = True
            finally:
                if member_conn.in_transaction:
                    member_conn.rollback()
                member_conn.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            member["status"] = "isolated_unavailable"
        results.append(member)
    degraded = any(not member["eligible"] for member in results)
    return {
        "status": "degraded" if degraded else "ok",
        "members": results,
        "summary": {
            "total": len(results),
            "eligible": sum(1 for member in results if member["eligible"]),
            "isolated": sum(1 for member in results if not member["eligible"]),
        },
    }
