import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .context import build_context_pack
from .db import connect, doctor, graph, ingest_repo, ingest_thread, reflect, remember, search, stale_check


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
        },
        ["text"],
    ),
    tool_schema(
        "brain_ingest_repo",
        "Index a local repository or folder into the Rta-Smriti brain.",
        {
            "path": {"type": "string", "description": "Local repository or folder path."},
            "project": {"type": "string", "description": "Project memory bank name."},
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
        "Report indexed files that are fresh, changed, or missing.",
        {"project": {"type": "string", "description": "Project memory bank name."}},
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
            )
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_repo":
            payload = ingest_repo(conn, Path(str(args["path"])), project=project)
            return text_result(json_text(payload), payload)
        if name == "brain_ingest_thread":
            payload = ingest_thread(conn, Path(str(args["path"])), project=project, title=args.get("title"))
            return text_result(json_text(payload), payload)
        if name == "brain_repo_map":
            payload = graph(conn, project=project, limit=int(args.get("limit", 100)))
            return text_result(json_text(payload), payload)
        if name == "brain_stale_check":
            payload = stale_check(conn, project=project)
            return text_result(json_text(payload), payload)
        if name == "brain_reflect":
            payload = reflect(conn, project=project)
            return text_result(json_text(payload), payload)
        if name == "brain_doctor":
            payload = doctor(conn)
            return text_result(json_text(payload), payload)
        raise KeyError(f"unknown tool: {name}")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
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
                name = params.get("name")
                if not name:
                    raise ValueError("tools/call requires params.name")
                result = self.call_tool(str(name), params.get("arguments") or {})
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
    for line in sys.stdin:
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
