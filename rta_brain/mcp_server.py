import argparse
import asyncio
import copy
import json
import stat
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import __version__
from .context import build_context_pack, build_continuation_prompt
from .continuity import append_event, ingest_codex_session, list_events, operational_readiness, reconcile_work_items, upsert_work_item
from .continuity_daemon import continuity_status, start_continuity, stop_continuity, validate_codex_session_binding
from .db import (
    connect, doctor, graph, graph_query, ingest_repo, ingest_thread, reflect, remember, remember_many,
    save_checkpoint, search, stale_check,
)
from .ingest import _lexical_root_for_candidate
from .diagnostics import retrieval_diagnostics
from .governance import build_operational_context, create_policy, list_policies, list_receipts, preflight, retire_policy
from .workspaces import get_workspace, list_workspaces, search_workspace, workspace_health


def tool_schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS = [
    tool_schema(
        "brain_search",
        "Search Rta-Smriti memories and indexed repository chunks.",
        {
            "query": {"type": "string", "description": "Search query."},
            "project": {"type": "string", "description": "Project memory bank name."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
        },
        ["query"],
    ),
    tool_schema(
        "brain_remember_batch",
        "Atomically store multiple durable, provenance-bearing memories.",
        {
            "project": {"type": "string"},
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 500,
                "items": {"type": "object"},
            },
        },
        ["items"],
    ),
    tool_schema(
        "brain_context_pack",
        "Build a compact task context pack with pramana tags and stale status.",
        {
            "task": {"type": "string", "description": "Task or question to prepare context for."},
            "project": {"type": "string", "description": "Project memory bank name."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
            "max_tokens": {"type": "integer", "minimum": 256, "maximum": 100000, "default": 4000},
        },
        ["task"],
    ),
    tool_schema(
        "brain_remember",
        "Store one durable memory with a Vedic pramana evidence tag.",
        {
            "text": {"type": "string", "description": "One atomic durable memory."},
            "type": {"type": "string", "description": "Memory type such as fact, decision, constraint, procedure, bug, or evidence."},
            "pramana": {
                "type": "string",
                "enum": ["pratyaksha", "sabda", "anumana", "smriti", "kalpana"],
                "description": "Evidence class: direct observation, trusted instruction, inference, prior memory, or hypothesis.",
            },
            "project": {"type": "string", "description": "Project memory bank name."},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.75},
            "priority": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            "provenance": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "source_hash": {"type": "string"},
                    "command": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "verification_status": {"type": "string", "enum": ["unverified", "verified", "failed", "stale"]},
                },
                "additionalProperties": False,
            },
        },
        ["text"],
    ),
    tool_schema(
        "brain_ingest_repo",
        "Index a local repository or folder into the Rta-Smriti brain.",
        {
            "path": {"type": "string", "description": "Local repository or folder path."},
            "project": {"type": "string", "description": "Project memory bank name."},
            "force": {"type": "boolean", "default": False, "description": "Hash every file even when the stat manifest is unchanged."},
            "repair_deep_stale": {"type": "boolean", "default": False, "description": "Hash every eligible file and re-index only content-drifted sources."},
        },
        ["path"],
    ),
    tool_schema(
        "brain_ingest_thread",
        "Index a long thread, transcript, JSONL session, or handoff file and promote durable observations.",
        {
            "path": {"type": "string", "description": "Local transcript, markdown, text, or JSONL session path."},
            "project": {"type": "string", "description": "Project memory bank name."},
            "title": {"type": "string", "description": "Human-readable thread or handoff title."},
        },
        ["path"],
    ),
    tool_schema(
        "brain_repo_map",
        "Return local graph nodes and edges for a project.",
        {
            "project": {"type": "string", "description": "Project memory bank name."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
    ),
    tool_schema(
        "brain_stale_check",
        "Compactly report freshness counts and anomalous files; fresh file rows are omitted by default.",
        {
            "project": {"type": "string", "description": "Project memory bank name."},
            "deep": {"type": "boolean", "default": False, "description": "Hash file contents instead of using the fast stat manifest."},
            "rehash": {"type": "boolean", "default": False, "description": "Bypass the stat-keyed hash cache; implies deep verification."},
            "include_fresh_details": {"type": "boolean", "default": False},
            "detail_limit": {"type": "integer", "minimum": 0, "maximum": 500, "default": 50},
        },
    ),
    tool_schema(
        "brain_checkpoint",
        "Save a structured continuation checkpoint for the next agent task.",
        {
            "project": {"type": "string"},
            "objective": {"type": "string"},
            "verified_evidence": {"type": "string"},
            "remaining_gaps": {"type": "string"},
            "next_action": {"type": "string"},
            "prohibited_repetition": {"type": "string"},
            "expected_version": {"type": "integer", "minimum": 0},
        },
        ["objective"],
    ),
    tool_schema(
        "brain_continuation_prompt",
        "Build a compact new-task prompt from the canonical root, Git state, freshness, and latest checkpoint.",
        {"project": {"type": "string"}},
    ),
    tool_schema(
        "brain_session_event",
        "Append an immutable, provenance-bearing operational event.",
        {
            "project": {"type": "string"},
            "session_id": {"type": "string"},
            "cursor": {"type": "string"},
            "event_type": {"type": "string"},
            "payload": {"type": "object"},
            "source": {"type": "string", "default": "agent"},
            "verification_status": {"type": "string", "enum": ["unverified", "verified", "failed", "stale"]},
        },
        ["session_id", "cursor", "event_type", "payload"],
    ),
    tool_schema(
        "brain_session_events",
        "Read append-only operational events for a project or session.",
        {"project": {"type": "string"}, "session_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}},
    ),
    tool_schema(
        "brain_ingest_codex_session",
        "Incrementally capture a local Codex JSONL transcript using a byte cursor.",
        {
            "project": {"type": "string"}, "path": {"type": "string"},
            "max_events": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 5000},
        },
        ["path"],
    ),
    tool_schema(
        "brain_work_item",
        "Create or update a structured asset, job, approval, blocker, or other work-state record.",
        {
            "project": {"type": "string"}, "item_type": {"type": "string"},
            "external_id": {"type": "string"}, "local_path": {"type": "string"},
            "qa_state": {"type": "string"}, "decision": {"type": "string"},
            "attempt_count": {"type": "integer", "minimum": 0}, "fallback": {"type": "string"},
            "next_action": {"type": "string"}, "metadata": {"type": "object"},
        },
        ["item_type", "external_id"],
    ),
    tool_schema("brain_reconcile", "Reconcile structured work state with the local filesystem.", {"project": {"type": "string"}}),
    tool_schema("brain_operational_readiness", "Distinguish database health from task continuation readiness.", {"project": {"type": "string"}}),
    tool_schema("brain_continuity_status", "Report managed Codex transcript capture and checkpoint lifecycle health.", {"project": {"type": "string"}}),
    tool_schema(
        "brain_continuity_control",
        "Start or stop managed Codex transcript capture for the canonical project root.",
        {
            "project": {"type": "string"},
            "action": {"type": "string", "enum": ["start", "stop"]},
            "interval": {"type": "number", "minimum": 0.1, "maximum": 3600},
            "inactivity": {"type": "number", "minimum": 1, "maximum": 604800},
        },
        ["action"],
    ),
    tool_schema(
        "brain_reflect",
        "Consolidate duplicate memories and flag simple contradictions so stale or unsafe context is not recalled as truth.",
        {"project": {"type": "string", "description": "Project memory bank name."}},
    ),
    tool_schema(
        "brain_graph_query",
        "Traverse bounded dependencies, dependents, impact, evidence, or relevance around an entity.",
        {
            "project": {"type": "string"},
            "target": {"type": "string"},
            "query_type": {"type": "string", "enum": ["dependencies", "dependents", "impact", "evidence", "relevance"], "default": "impact"},
            "depth": {"type": "integer", "minimum": 0, "maximum": 4, "default": 2},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
        ["target"],
    ),
    tool_schema(
        "brain_retrieval_diagnostics",
        "Explain retrieval mode, index coverage, ranking components, evidence hashes, freshness, and latency.",
        {
            "project": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
        },
        ["query"],
    ),
    tool_schema(
        "brain_workspace_search",
        "Search every project in an operator-defined multi-repository workspace.",
        {
            "workspace": {"type": "string"},
            "query": {"type": "string"},
            "limit_per_project": {"type": "integer", "minimum": 1, "maximum": 20, "default": 4},
        },
        ["workspace", "query"],
    ),
    tool_schema(
        "brain_workspace_list",
        "List multi-repository workspaces or inspect one workspace.",
        {"workspace": {"type": "string"}},
    ),
    tool_schema(
        "brain_workspace_health",
        "Report member availability for one multi-repository workspace without exposing local database paths.",
        {"workspace": {"type": "string"}},
        ["workspace"],
    ),
    tool_schema(
        "brain_policy_add",
        "Create a typed, provenance-bearing pre-action governance policy.",
        {
            "project": {"type": "string"},
            "kind": {"type": "string", "enum": ["constraint", "failed_approach", "fragile_path", "required_check", "prohibited_repetition"]},
            "statement": {"type": "string"},
            "effect": {"type": "string", "enum": ["warn", "block"], "default": "warn"},
            "action_contains": {"type": "string"},
            "path_glob": {"type": "string"},
            "required_check": {"type": "string"},
            "pramana": {"type": "string", "enum": ["pratyaksha", "sabda", "anumana", "smriti", "kalpana"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "provenance": {"type": "object"},
            "overrideable": {"type": "boolean"},
            "expires_at": {"type": "string"},
        },
        ["kind", "statement"],
    ),
    tool_schema(
        "brain_policy_list",
        "List active or retired governance policies for a project.",
        {"project": {"type": "string"}, "include_retired": {"type": "boolean", "default": False}},
    ),
    tool_schema(
        "brain_policy_retire",
        "Explicitly retire an active governance policy.",
        {"project": {"type": "string"}, "policy_id": {"type": "integer"}, "reason": {"type": "string"}},
        ["policy_id", "reason"],
    ),
    tool_schema(
        "brain_preflight",
        "Return allow, warn, or block before an action; overrides create receipts.",
        {
            "project": {"type": "string"},
            "action": {"type": "string"},
            "path": {"type": "string"},
            "include_operational_context": {"type": "boolean", "default": True},
        },
        ["action"],
    ),
    tool_schema(
        "brain_governance_receipts",
        "List immutable governance override receipts.",
        {"project": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}},
    ),
    tool_schema(
        "brain_doctor",
        "Return Rta-Smriti brain health and count information.",
        {"project": {"type": "string", "description": "Also evaluate task continuation readiness."}},
    ),
]

OWNER_ONLY_GOVERNANCE_TOOLS = {"brain_policy_add", "brain_policy_retire"}
MEMORY_WRITE_TOOLS = {"brain_remember", "brain_remember_batch", "brain_checkpoint", "brain_reflect"}
REPO_INGESTION_TOOLS = {"brain_ingest_repo"}
THREAD_INGESTION_TOOLS = {"brain_ingest_thread"}
PROJECT_BOUND_READ_TOOLS = {
    "brain_search",
    "brain_context_pack",
    "brain_repo_map",
    "brain_stale_check",
    "brain_continuation_prompt",
    "brain_graph_query",
    "brain_retrieval_diagnostics",
    "brain_policy_list",
    "brain_preflight",
    "brain_governance_receipts",
}
TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}

MAX_MCP_FRAME_BYTES = 1_048_576
MAX_MCP_JSON_NESTING = 64
MAX_MCP_OUTSTANDING_REQUESTS = 32
MAX_MCP_OUTSTANDING_BYTES = MAX_MCP_FRAME_BYTES * 4
SUPPORTED_MCP_PROTOCOL_VERSIONS = ("2025-06-18", "2024-11-05")


def _agent_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    exposed = copy.deepcopy(tool)
    properties = exposed["inputSchema"]["properties"]
    properties.pop("project", None)
    if exposed["name"] == "brain_ingest_repo":
        properties.pop("path", None)
        exposed["inputSchema"]["required"] = [
            name for name in exposed["inputSchema"].get("required", []) if name != "path"
        ]
        exposed["description"] += " Refreshes only the canonical root already bound to this project."
    if exposed["name"] in {"brain_remember", "brain_remember_batch"}:
        exposed["description"] += " Agent assertions are stored as unverified inference."
    if exposed["name"] == "brain_remember":
        properties["pramana"] = {
            "type": "string",
            "enum": ["anumana"],
            "default": "anumana",
            "description": "Agent inference; MCP cannot assert direct or verified evidence.",
        }
        properties["confidence"]["maximum"] = 0.75
        properties["provenance"] = {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string"},
                "metadata": {"type": "object"},
                "verification_status": {
                    "type": "string",
                    "enum": ["unverified"],
                    "default": "unverified",
                },
            },
            "additionalProperties": False,
            "description": "Unverified agent provenance; source authority cannot be asserted over MCP.",
        }
    return exposed


def _path_is_link_or_reparse(path: Path) -> bool:
    details = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = int(getattr(details, "st_file_attributes", 0))
    return stat.S_ISLNK(details.st_mode) or bool(reparse_flag and file_attributes & reparse_flag)


def _canonical_thread_root(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    if _path_is_link_or_reparse(candidate):
        raise ValueError(f"thread root contains a link or reparse point: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"thread root is not a directory: {resolved}")
    return resolved


def _confined_thread_path(path: Path, allowed_roots: tuple[Path, ...]) -> tuple[Path, Path]:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        raise ValueError("thread path must be absolute")
    lexical = candidate.absolute()
    if _path_is_link_or_reparse(lexical):
        raise ValueError(f"thread path contains a link or reparse point: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"thread path does not exist or cannot be resolved: {lexical}") from exc
    matched_root = next(
        (root for root in allowed_roots if resolved == root or resolved.is_relative_to(root)),
        None,
    )
    if matched_root is None:
        raise ValueError(f"thread path is outside configured thread roots: {resolved}")
    try:
        _lexical_root_for_candidate(matched_root, lexical)
    except (OSError, ValueError) as exc:
        raise ValueError(f"thread path contains a link or reparse point: {lexical}") from exc
    details = resolved.lstat()
    if not stat.S_ISREG(details.st_mode):
        raise ValueError(f"thread path is not a regular file: {resolved}")
    if int(getattr(details, "st_nlink", 1)) != 1:
        raise ValueError(f"thread path is a hardlink and cannot be ingested: {resolved}")
    return resolved, matched_root


def _agent_memory_provenance(value: Any) -> dict[str, Any]:
    if value is not None and not isinstance(value, dict):
        raise ValueError("memory provenance must be an object")
    supplied = value or {}
    metadata = supplied.get("metadata") if isinstance(supplied.get("metadata"), dict) else {}
    return {
        "command": supplied.get("command"),
        "timestamp": supplied.get("timestamp"),
        "verification_status": "unverified",
        "metadata": metadata,
    }


def _agent_memory_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("each memory batch item must be an object")
    item = dict(value)
    item["pramana"] = "anumana"
    item["confidence"] = min(0.75, float(item.get("confidence", 0.75)))
    item["provenance"] = _agent_memory_provenance(item.get("provenance"))
    return item


def _json_nesting_exceeds(frame: bytes, maximum: int = MAX_MCP_JSON_NESTING) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for byte in frame:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > maximum:
                return True
        elif byte in (0x5D, 0x7D):
            depth = max(0, depth - 1)
    return False


def parse_request_frame(frame: bytes) -> Any:
    if _json_nesting_exceeds(frame):
        raise ValueError(f"JSON nesting exceeds the {MAX_MCP_JSON_NESTING} level limit")
    try:
        return json.loads(frame)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds parser limits") from exc


def text_result(text: str, structured: Any | None = None) -> dict[str, Any]:
    result = {"content": [{"type": "text", "text": text}], "isError": False}
    if structured is not None:
        result["structuredContent"] = structured
    return result


def json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


class RtaBrainMcpServer:
    def __init__(
        self,
        db_path: Path | None = None,
        default_project: str | None = None,
        *,
        brain_dir: Path | None = None,
        allow_memory_writes: bool = False,
        allow_repo_ingestion: bool = False,
        allow_thread_ingestion: bool = False,
        allowed_thread_roots: tuple[Path, ...] = (),
    ):
        if (db_path is None) == (brain_dir is None):
            raise ValueError("configure exactly one of db_path or brain_dir")
        self.db_path = db_path.expanduser().resolve() if db_path else None
        self.brain_dir = brain_dir.expanduser().resolve() if brain_dir else None
        self.default_project = str(default_project or "default").strip() if self.db_path else default_project
        if self.db_path is not None and not self.default_project:
            raise ValueError("default project must not be empty")
        self.allowed_thread_roots = tuple(_canonical_thread_root(root) for root in allowed_thread_roots)
        if allow_thread_ingestion and not self.allowed_thread_roots:
            raise ValueError("thread ingestion requires at least one configured thread root")
        if self.brain_dir is not None:
            enabled = set(TOOL_BY_NAME)
        else:
            enabled = set(PROJECT_BOUND_READ_TOOLS)
            enabled.update({"brain_session_events", "brain_reconcile", "brain_operational_readiness", "brain_continuity_status"})
        if allow_memory_writes:
            enabled.update(MEMORY_WRITE_TOOLS)
            enabled.update({"brain_session_event", "brain_work_item", "brain_continuity_control"})
        if allow_repo_ingestion:
            enabled.update(REPO_INGESTION_TOOLS)
        if allow_thread_ingestion:
            enabled.update(THREAD_INGESTION_TOOLS)
            enabled.add("brain_ingest_codex_session")
        self.enabled_tools = frozenset(enabled)
        self.agent_tools = [
            (copy.deepcopy(TOOL_BY_NAME[name]) if self.brain_dir is not None else _agent_tool_schema(TOOL_BY_NAME[name]))
            for name in TOOL_BY_NAME if name in enabled
        ]

    def _bound_project(self, args: dict[str, Any]) -> str:
        requested = args.get("project")
        if requested is not None and str(requested).strip() != self.default_project:
            raise ValueError(
                f"MCP server is bound to project '{self.default_project}'; client project overrides are rejected"
            )
        return self.default_project

    def _bound_repository_root(self, conn, args: dict[str, Any], project: str | None = None) -> Path:
        project_name = project or self.default_project
        row = conn.execute(
            "SELECT root_path FROM projects WHERE name = ?", (project_name,),
        ).fetchone()
        if not row or not row["root_path"]:
            raise ValueError(
                f"project '{project_name}' has no canonical repository root; bootstrap it before MCP ingestion"
            )
        root = Path(str(row["root_path"])).expanduser().resolve()
        requested = args.get("path")
        if requested is not None and Path(str(requested)).expanduser().resolve() != root:
            raise ValueError(
                f"repository ingestion is confined to the canonical project root: {root}"
            )
        return root

    def _open_project(self, project: str | None):
        if self.db_path is not None:
            if not self.default_project:
                raise ValueError("single-database MCP mode requires a default project")
            requested = str(project or self.default_project).strip()
            if requested != self.default_project:
                raise ValueError(
                    f"MCP server is bound to project '{self.default_project}'; client project overrides are rejected"
                )
            return connect(self.db_path), self.db_path, self.default_project
        if not project:
            raise ValueError("project is required when using the multi-project brain gateway")
        if not self.brain_dir or not self.brain_dir.is_dir() or self.brain_dir.is_symlink():
            raise ValueError("brain directory is not a safe directory")
        matches = []
        for candidate in self.brain_dir.glob("*.sqlite"):
            if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_nlink > 1:
                continue
            before = candidate.stat()
            conn = connect(candidate)
            after = candidate.stat()
            if before.st_dev != after.st_dev or before.st_ino != after.st_ino:
                conn.close()
                raise ValueError("brain database changed identity while routing the MCP call")
            if conn.execute("SELECT 1 FROM projects WHERE name = ?", (str(project),)).fetchone():
                matches.append((conn, candidate.resolve()))
            else:
                conn.close()
        if not matches:
            raise ValueError(f"unknown project in brain directory: {project}")
        if len(matches) > 1:
            for conn, _path in matches:
                conn.close()
            raise ValueError(f"project name is ambiguous across brain databases: {project}")
        conn, path = matches[0]
        return conn, path, str(project)

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        if name not in TOOL_BY_NAME:
            raise KeyError(f"unknown tool: {name}")
        if name not in self.enabled_tools:
            raise ValueError(f"MCP tool '{name}' is not enabled by server startup capabilities")
        conn, db_path, project = self._open_project(args.get("project") or self.default_project)
        try:
            return self._call_tool_with_connection(conn, name, args, db_path=db_path, resolved_project=project)
        finally:
            conn.close()

    def _call_tool_with_connection(
        self, conn, name: str, args: dict[str, Any], *, db_path: Path, resolved_project: str
    ) -> dict[str, Any]:
        project = resolved_project
        if name in OWNER_ONLY_GOVERNANCE_TOOLS:
            raise ValueError("governance policy mutation requires an owner-controlled CLI or dashboard session")
        if name == "brain_preflight" and args.get("override_reason"):
            raise ValueError("governance override requires an owner-controlled CLI or dashboard session")
        if name == "brain_preflight" and args.get("completed_checks"):
            raise ValueError("governance check attestation requires an owner-controlled CLI or dashboard session")
        if name == "brain_search":
            payload = search(conn, str(args["query"]), project=project, limit=int(args.get("limit", 8)))
            return text_result(json_text(payload), payload)
        if name == "brain_context_pack":
            text = build_context_pack(
                conn, str(args["task"]), project=project, limit=int(args.get("limit", 8)),
                max_tokens=int(args.get("max_tokens", 4_000)),
            )
            return text_result(text)
        if name == "brain_remember":
            payload = remember(
                conn,
                str(args["text"]),
                project=project,
                memory_type=str(args.get("type", "fact")),
                pramana="anumana",
                confidence=min(0.75, float(args.get("confidence", 0.75))),
                priority=int(args.get("priority", 5)),
                provenance=_agent_memory_provenance(args.get("provenance")),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_remember_batch":
            payload = remember_many(conn, [_agent_memory_item(item) for item in args["items"]], project=project)
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_repo":
            root = self._bound_repository_root(conn, args, project)
            force = bool(args.get("force", False))
            repair_deep_stale = bool(args.get("repair_deep_stale", False))
            if not force and not repair_deep_stale:
                freshness = stale_check(conn, project=project, detail_limit=0)
                if freshness.get("state") == "fresh":
                    payload = {
                        "status": "ok",
                        "project": project,
                        "root": str(root),
                        "state": "fresh",
                        "indexed_files": int(freshness.get("fresh") or 0),
                        "updated_files": 0,
                        "unchanged_files": int(freshness.get("fresh") or 0),
                        "removed_files": 0,
                        "skipped_files": 0,
                        "blocked_files": int(freshness.get("uninspectable") or 0),
                        "manifest_unchanged": True,
                        "mcp_short_circuit": True,
                        "freshness": freshness,
                    }
                    return text_result(json_text(payload), payload)
            payload = ingest_repo(
                conn,
                root,
                project=project,
                force=force,
                repair_deep_stale=repair_deep_stale,
            )
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_thread":
            if not self.allowed_thread_roots:
                raise ValueError("thread ingestion roots are not configured for this MCP server")
            thread_path, thread_root = _confined_thread_path(
                Path(str(args["path"])), self.allowed_thread_roots,
            )
            payload = ingest_thread(
                conn, thread_path, project=project, title=args.get("title"), root=thread_root,
            )
            return text_result(json_text(payload), payload)
        if name == "brain_repo_map":
            payload = graph(conn, project=project, limit=int(args.get("limit", 100)))
            return text_result(json_text(payload), payload)
        if name == "brain_graph_query":
            payload = graph_query(
                conn, project=project, query_type=str(args.get("query_type", "impact")),
                target=str(args["target"]), depth=int(args.get("depth", 2)), limit=int(args.get("limit", 100)),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_retrieval_diagnostics":
            payload = retrieval_diagnostics(
                conn, str(args["query"]), project=project, limit=int(args.get("limit", 8)),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_workspace_search":
            payload = search_workspace(
                conn, workspace=str(args["workspace"]), query=str(args["query"]),
                limit_per_project=int(args.get("limit_per_project", 4)),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_workspace_list":
            payload = get_workspace(conn, str(args["workspace"])) if args.get("workspace") else list_workspaces(conn)
            return text_result(json_text(payload), payload)
        if name == "brain_workspace_health":
            payload = workspace_health(conn, str(args["workspace"]))
            return text_result(json_text(payload), payload)
        if name == "brain_stale_check":
            payload = stale_check(
                conn,
                project=project,
                deep=bool(args.get("deep", False) or args.get("rehash", False)),
                refresh_hashes=bool(args.get("rehash", False)),
                detail_limit=int(args.get("detail_limit", 50)),
                include_fresh_details=bool(args.get("include_fresh_details", False)),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_checkpoint":
            payload = save_checkpoint(
                conn,
                project=project,
                objective=str(args["objective"]),
                verified_evidence=str(args.get("verified_evidence", "")),
                remaining_gaps=str(args.get("remaining_gaps", "")),
                next_action=str(args.get("next_action", "")),
                prohibited_repetition=str(args.get("prohibited_repetition", "")),
                expected_version=args.get("expected_version"),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_continuation_prompt":
            return text_result(build_continuation_prompt(conn, project=project))
        if name == "brain_session_event":
            payload = append_event(
                conn, project, str(args["session_id"]), str(args["cursor"]),
                str(args["event_type"]), dict(args["payload"]), source=str(args.get("source", "agent")),
                verification_status=str(args.get("verification_status", "unverified")),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_session_events":
            payload = list_events(conn, project, session_id=args.get("session_id"), limit=int(args.get("limit", 100)))
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_codex_session":
            row = conn.execute("SELECT root_path FROM projects WHERE name = ?", (project,)).fetchone()
            if not row or not row["root_path"]:
                raise ValueError("project has no canonical root for transcript ingestion")
            session_path = Path(str(args["path"]))
            session_id = validate_codex_session_binding(
                session_path, Path.home() / ".codex" / "sessions", Path(row["root_path"]),
            )
            payload = ingest_codex_session(
                conn, session_path, project,
                session_id=session_id, max_events=int(args.get("max_events", 5000)),
                expected_project_root=Path(row["root_path"]),
                expected_sessions_root=Path.home() / ".codex" / "sessions",
            )
            return text_result(json_text(payload), payload)
        if name == "brain_work_item":
            payload = upsert_work_item(
                conn, project, str(args["item_type"]), str(args["external_id"]),
                local_path=args.get("local_path"), qa_state=str(args.get("qa_state", "unknown")),
                decision=str(args.get("decision", "pending")), attempt_count=int(args.get("attempt_count", 0)),
                fallback=str(args.get("fallback", "")), next_action=str(args.get("next_action", "")),
                metadata=args.get("metadata"),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_reconcile":
            payload = reconcile_work_items(conn, project)
            return text_result(json_text(payload), payload)
        if name == "brain_operational_readiness":
            payload = operational_readiness(conn, project, lifecycle=continuity_status(db_path, project))
            return text_result(json_text(payload), payload)
        if name == "brain_continuity_status":
            payload = continuity_status(db_path, project)
            return text_result(json_text(payload), payload)
        if name == "brain_continuity_control":
            action = str(args["action"])
            if action == "stop":
                payload = stop_continuity(db_path, project)
            elif action == "start":
                row = conn.execute("SELECT root_path FROM projects WHERE name = ?", (project,)).fetchone()
                if not row or not row["root_path"]:
                    raise ValueError("project has no canonical root for continuity capture")
                payload = start_continuity(
                    db_path,
                    Path(row["root_path"]),
                    project,
                    Path.home() / ".codex" / "sessions",
                    interval_seconds=float(args.get("interval", 5.0)),
                    inactivity_seconds=float(args.get("inactivity", 900.0)),
                )
            else:
                raise ValueError("continuity action must be start or stop")
            return text_result(json_text(payload), payload)
        if name == "brain_reflect":
            payload = reflect(conn, project=project)
            return text_result(json_text(payload), payload)
        if name == "brain_policy_add":
            payload = create_policy(
                conn,
                project=project,
                kind=str(args["kind"]),
                statement=str(args["statement"]),
                effect=str(args.get("effect", "warn")),
                action_contains=str(args.get("action_contains", "")),
                path_glob=str(args.get("path_glob", "")),
                required_check=str(args.get("required_check", "")),
                pramana=str(args.get("pramana", "smriti")),
                confidence=float(args.get("confidence", 0.75)),
                provenance=args.get("provenance"),
                overrideable=bool(args.get("overrideable", True)),
                expires_at=args.get("expires_at"),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_policy_list":
            payload = list_policies(conn, project=project, include_retired=bool(args.get("include_retired", False)))
            return text_result(json_text(payload), payload)
        if name == "brain_policy_retire":
            payload = retire_policy(
                conn, project=project, policy_id=int(args["policy_id"]), reason=str(args["reason"]),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_preflight":
            payload = preflight(
                conn,
                project=project,
                action=str(args["action"]),
                path=args.get("path"),
                completed_checks=[],
                override_reason=None,
                actor="agent",
                operational_context=(
                    build_operational_context(conn, project, db_path=db_path)
                    if bool(args.get("include_operational_context", True)) else None
                ),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_governance_receipts":
            payload = list_receipts(conn, project=project, limit=int(args.get("limit", 100)))
            return text_result(json_text(payload), payload)
        if name == "brain_doctor":
            payload = doctor(conn)
            if project:
                payload["operational"] = operational_readiness(
                    conn, project, lifecycle=continuity_status(db_path, project),
                )
            return text_result(json_text(payload), payload)
        raise KeyError(f"unknown tool: {name}")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return self.error(None, -32600, "invalid request: JSON-RPC frame must be an object")
        method = request.get("method")
        request_id = request.get("id")
        notification = "id" not in request
        respond = lambda payload: None if notification else payload
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return respond(self.error(request_id, -32600, "invalid request: jsonrpc must be '2.0' and method must be a string"))
        try:
            if method == "initialize":
                requested_version = (request.get("params") or {}).get("protocolVersion")
                negotiated_version = (
                    requested_version
                    if requested_version in SUPPORTED_MCP_PROTOCOL_VERSIONS
                    else SUPPORTED_MCP_PROTOCOL_VERSIONS[0]
                )
                return respond({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": negotiated_version,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "rta-smriti-brain", "version": __version__},
                    },
                })
            if method == "tools/list":
                return respond({"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.agent_tools}})
            if method == "tools/call":
                params = request.get("params") or {}
                if not isinstance(params, dict):
                    raise ValueError("tools/call params must be an object")
                name = params.get("name")
                if not name:
                    raise ValueError("tools/call requires params.name")
                arguments = params.get("arguments") or {}
                if not isinstance(arguments, dict):
                    raise ValueError("tools/call arguments must be an object")
                result = self.call_tool(str(name), arguments)
                return respond({"jsonrpc": "2.0", "id": request_id, "result": result})
            if method == "ping":
                return respond({"jsonrpc": "2.0", "id": request_id, "result": {}})
            return respond(self.error(request_id, -32601, f"method not found: {method}"))
        except KeyError as exc:
            return respond(self.error(request_id, -32601, str(exc).strip("'")))
        except Exception as exc:
            return respond(self.error(request_id, -32000, str(exc), {"type": exc.__class__.__name__}))

    async def handle_async(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Keep stdio responsive while SQLite, parsing, hashing, or embedding work runs."""
        if isinstance(request, dict) and request.get("method") == "tools/call":
            return await asyncio.to_thread(self.handle, request)
        return self.handle(request)

    @staticmethod
    def error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if data is not None:
            payload["error"]["data"] = data
        return payload


MUTATING_TOOLS = {
    "brain_remember",
    "brain_remember_batch",
    "brain_ingest_repo",
    "brain_ingest_thread",
    "brain_checkpoint",
    "brain_session_event",
    "brain_ingest_codex_session",
    "brain_work_item",
    "brain_continuity_control",
    "brain_reflect",
}


def _tool_name(request: dict[str, Any]) -> str | None:
    if not isinstance(request, dict) or request.get("method") != "tools/call":
        return None
    params = request.get("params")
    return str(params.get("name")) if isinstance(params, dict) and params.get("name") else None


class McpRequestScheduler:
    """Run blocking tool calls concurrently while preserving mutation causality."""

    def __init__(
        self,
        server: RtaBrainMcpServer,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        max_concurrency: int = 4,
        max_outstanding: int = MAX_MCP_OUTSTANDING_REQUESTS,
        max_outstanding_bytes: int = MAX_MCP_OUTSTANDING_BYTES,
    ) -> None:
        self.server = server
        self.emit = emit
        self.capacity = asyncio.Semaphore(max(1, int(max_concurrency)))
        self.max_outstanding = max(1, int(max_outstanding))
        self.max_outstanding_bytes = max(1, int(max_outstanding_bytes))
        self._admission = asyncio.Condition()
        self._outstanding = 0
        self._outstanding_bytes = 0
        self.peak_outstanding = 0
        self.peak_outstanding_bytes = 0
        self.pending: set[asyncio.Task] = set()
        self.latest_mutation: asyncio.Task | None = None

    async def _process(self, request: Any, dependency: asyncio.Task | None) -> None:
        if dependency is not None:
            await dependency
        async with self.capacity:
            response = await self.server.handle_async(request)
        if response is not None:
            await self.emit(response)

    async def _release(self, frame_bytes: int) -> None:
        async with self._admission:
            self._outstanding -= 1
            self._outstanding_bytes -= frame_bytes
            self._admission.notify_all()

    async def _process_and_release(
        self, request: Any, dependency: asyncio.Task | None, frame_bytes: int
    ) -> None:
        try:
            await self._process(request, dependency)
        finally:
            await self._release(frame_bytes)

    async def submit(self, request: Any, frame_bytes: int = 0) -> None:
        frame_bytes = max(0, int(frame_bytes))
        if frame_bytes > self.max_outstanding_bytes:
            raise ValueError("request exceeds the scheduler byte limit")
        async with self._admission:
            await self._admission.wait_for(
                lambda: self._outstanding < self.max_outstanding
                and self._outstanding_bytes + frame_bytes <= self.max_outstanding_bytes
            )
            self._outstanding += 1
            self._outstanding_bytes += frame_bytes
            self.peak_outstanding = max(self.peak_outstanding, self._outstanding)
            self.peak_outstanding_bytes = max(self.peak_outstanding_bytes, self._outstanding_bytes)
        tool_name = _tool_name(request)
        is_mutation = tool_name in MUTATING_TOOLS
        is_tool_call = isinstance(request, dict) and request.get("method") == "tools/call"
        dependency = self.latest_mutation if (is_mutation or is_tool_call) else None
        task = asyncio.create_task(self._process_and_release(request, dependency, frame_bytes))
        if is_mutation:
            self.latest_mutation = task
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def close(self) -> None:
        if self.pending:
            await asyncio.gather(*tuple(self.pending))


async def serve_stdio_async(
    db_path: Path | None,
    default_project: str | None,
    *,
    brain_dir: Path | None = None,
    allow_memory_writes: bool = False,
    allow_repo_ingestion: bool = False,
    allow_thread_ingestion: bool = False,
    allowed_thread_roots: tuple[Path, ...] = (),
) -> int:
    server = RtaBrainMcpServer(
        db_path=db_path,
        default_project=default_project,
        brain_dir=brain_dir,
        allow_memory_writes=allow_memory_writes,
        allow_repo_ingestion=allow_repo_ingestion,
        allow_thread_ingestion=allow_thread_ingestion,
        allowed_thread_roots=allowed_thread_roots,
    )
    stream = sys.stdin.buffer
    write_lock = asyncio.Lock()

    async def emit(response: dict[str, Any]) -> None:
        async with write_lock:
            print(json.dumps(response, separators=(",", ":")), flush=True)

    scheduler = McpRequestScheduler(server, emit, max_concurrency=4)

    while True:
        line = await asyncio.to_thread(stream.readline, MAX_MCP_FRAME_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_MCP_FRAME_BYTES:
            while line and not line.endswith(b"\n"):
                line = await asyncio.to_thread(stream.readline, MAX_MCP_FRAME_BYTES + 1)
            response = RtaBrainMcpServer.error(None, -32600, f"request frame exceeds {MAX_MCP_FRAME_BYTES} bytes")
            await emit(response)
            continue
        if not line.strip():
            continue
        try:
            request = parse_request_frame(line)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError, MemoryError) as exc:
            response = RtaBrainMcpServer.error(None, -32700, f"parse error: {exc}")
            await emit(response)
        else:
            await scheduler.submit(request, frame_bytes=len(line))
    await scheduler.close()
    return 0


def serve_stdio(
    db_path: Path | None,
    default_project: str | None,
    *,
    brain_dir: Path | None = None,
    allow_memory_writes: bool = False,
    allow_repo_ingestion: bool = False,
    allow_thread_ingestion: bool = False,
    allowed_thread_roots: tuple[Path, ...] = (),
) -> int:
    return asyncio.run(serve_stdio_async(
        db_path,
        default_project,
        brain_dir=brain_dir,
        allow_memory_writes=allow_memory_writes,
        allow_repo_ingestion=allow_repo_ingestion,
        allow_thread_ingestion=allow_thread_ingestion,
        allowed_thread_roots=allowed_thread_roots,
    ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rta-brain-mcp", description="Rta-Smriti Brain MCP stdio server")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", help="Path to one SQLite brain file")
    source.add_argument("--brain-dir", help="Directory of project-scoped SQLite brain files")
    parser.add_argument("--project", default="default", help="Default project memory bank for single-database mode")
    parser.add_argument(
        "--allow-memory-writes", action="store_true",
        help="Allow agent-authored memories, checkpoints, and reflection (disabled by default)",
    )
    parser.add_argument(
        "--allow-repo-ingestion", action="store_true",
        help="Allow repository ingestion (disabled by default)",
    )
    parser.add_argument(
        "--allow-thread-ingestion", action="store_true",
        help="Allow thread ingestion from explicitly configured roots (disabled by default)",
    )
    parser.add_argument(
        "--allow-thread-root", action="append", default=[], metavar="PATH",
        help="Canonical directory allowed for thread ingestion; may be repeated",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.brain_dir and (args.allow_memory_writes or args.allow_repo_ingestion or args.allow_thread_ingestion or args.allow_thread_root):
        parser.error("capability flags are only valid with --db single-project mode")
    if args.allow_thread_ingestion and not args.allow_thread_root:
        parser.error("--allow-thread-ingestion requires at least one --allow-thread-root")
    return serve_stdio(
        Path(args.db) if args.db else None,
        args.project,
        brain_dir=Path(args.brain_dir) if args.brain_dir else None,
        allow_memory_writes=args.allow_memory_writes,
        allow_repo_ingestion=args.allow_repo_ingestion,
        allow_thread_ingestion=args.allow_thread_ingestion,
        allowed_thread_roots=tuple(Path(root) for root in args.allow_thread_root),
    )


if __name__ == "__main__":
    raise SystemExit(main())
