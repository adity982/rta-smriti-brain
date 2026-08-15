import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .context import build_context_pack, build_continuation_prompt
from .db import connect, doctor, graph, ingest_repo, ingest_thread, reflect, remember, save_checkpoint, search, stale_check


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
        "brain_context_pack",
        "Build a compact task context pack with pramana tags and stale status.",
        {
            "task": {"type": "string", "description": "Task or question to prepare context for."},
            "project": {"type": "string", "description": "Project memory bank name."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
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
        },
        ["objective"],
    ),
    tool_schema(
        "brain_continuation_prompt",
        "Build a compact new-task prompt from the canonical root, Git state, freshness, and latest checkpoint.",
        {"project": {"type": "string"}},
    ),
    tool_schema(
        "brain_reflect",
        "Consolidate duplicate memories and flag simple contradictions so stale or unsafe context is not recalled as truth.",
        {"project": {"type": "string", "description": "Project memory bank name."}},
    ),
    tool_schema(
        "brain_doctor",
        "Return Rta-Smriti brain health and count information.",
        {},
    ),
]

MAX_MCP_FRAME_BYTES = 1_048_576


def text_result(text: str, structured: Any | None = None) -> dict[str, Any]:
    result = {"content": [{"type": "text", "text": text}], "isError": False}
    if structured is not None:
        result["structuredContent"] = structured
    return result


def json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


class RtaBrainMcpServer:
    def __init__(self, db_path: Path, default_project: str):
        self.db_path = db_path
        self.default_project = default_project

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        conn = connect(self.db_path)
        project = args.get("project") or self.default_project
        if name == "brain_search":
            payload = search(conn, str(args["query"]), project=project, limit=int(args.get("limit", 8)))
            return text_result(json_text(payload), payload)
        if name == "brain_context_pack":
            text = build_context_pack(conn, str(args["task"]), project=project, limit=int(args.get("limit", 8)))
            return text_result(text)
        if name == "brain_remember":
            payload = remember(
                conn,
                str(args["text"]),
                project=project,
                memory_type=str(args.get("type", "fact")),
                pramana=str(args.get("pramana", "smriti")),
                confidence=float(args.get("confidence", 0.75)),
                priority=int(args.get("priority", 5)),
                provenance=args.get("provenance"),
            )
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_repo":
            payload = ingest_repo(conn, Path(str(args["path"])), project=project, force=bool(args.get("force", False)))
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_thread":
            payload = ingest_thread(conn, Path(str(args["path"])), project=project, title=args.get("title"))
            return text_result(json_text(payload), payload)
        if name == "brain_repo_map":
            payload = graph(conn, project=project, limit=int(args.get("limit", 100)))
            return text_result(json_text(payload), payload)
        if name == "brain_stale_check":
            payload = stale_check(
                conn,
                project=project,
                deep=bool(args.get("deep", False)),
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
            )
            return text_result(json_text(payload), payload)
        if name == "brain_continuation_prompt":
            return text_result(build_continuation_prompt(conn, project=project))
        if name == "brain_reflect":
            payload = reflect(conn, project=project)
            return text_result(json_text(payload), payload)
        if name == "brain_doctor":
            payload = doctor(conn)
            return text_result(json_text(payload), payload)
        raise KeyError(f"unknown tool: {name}")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return self.error(None, -32600, "invalid request: JSON-RPC frame must be an object")
        method = request.get("method")
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self.error(request_id, -32600, "invalid request: jsonrpc must be '2.0' and method must be a string")
        if method and method.startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                requested_version = (request.get("params") or {}).get("protocolVersion") or "2025-06-18"
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": requested_version,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "rta-smriti-brain", "version": __version__},
                    },
                }
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
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
                return {"jsonrpc": "2.0", "id": request_id, "result": result}
            if method == "ping":
                return {"jsonrpc": "2.0", "id": request_id, "result": {}}
            return self.error(request_id, -32601, f"method not found: {method}")
        except KeyError as exc:
            return self.error(request_id, -32601, str(exc).strip("'"))
        except Exception as exc:
            return self.error(request_id, -32000, str(exc), {"type": exc.__class__.__name__})

    @staticmethod
    def error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        if data is not None:
            payload["error"]["data"] = data
        return payload


def serve_stdio(db_path: Path, default_project: str) -> int:
    server = RtaBrainMcpServer(db_path=db_path, default_project=default_project)
    stream = sys.stdin.buffer
    while True:
        line = stream.readline(MAX_MCP_FRAME_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_MCP_FRAME_BYTES:
            while line and not line.endswith(b"\n"):
                line = stream.readline(MAX_MCP_FRAME_BYTES + 1)
            response = RtaBrainMcpServer.error(None, -32600, f"request frame exceeds {MAX_MCP_FRAME_BYTES} bytes")
            print(json.dumps(response, separators=(",", ":")), flush=True)
            continue
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = RtaBrainMcpServer.error(None, -32700, f"parse error: {exc}")
        else:
            response = server.handle(request)
        if response is not None:
            print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rta-brain-mcp", description="Rta-Smriti Brain MCP stdio server")
    parser.add_argument("--db", required=True, help="Path to SQLite brain file")
    parser.add_argument("--project", default="default", help="Default project memory bank")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return serve_stdio(Path(args.db), args.project)


if __name__ == "__main__":
    raise SystemExit(main())
