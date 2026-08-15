import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .context import build_context_pack, build_continuation_prompt
from .console import publish_readiness, run_dashboard
from .db import (
    connect, doctor, get_project_settings, graph, ingest_repo, ingest_thread, init_project, reflect,
    remember, save_checkpoint, search, stale_check, update_project_settings,
)
from .project import bootstrap_project, install_local, mcp_config_payload, projects_list, self_check
from .watch import watch_repository


def default_db_path() -> Path:
    return Path.cwd() / ".rta-smriti" / "brain.sqlite"


def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def emit(payload, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif isinstance(payload, str):
        print(payload, end="" if payload.endswith("\n") else "\n")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rta-brain", description="Rta-Smriti local project brain")
    parser.add_argument("--db", default=str(default_db_path()), help="Path to SQLite brain file")
    parser.add_argument("--json", action="store_true", help="Emit stable JSON")
    parser.add_argument("--version", action="version", version=f"rta-brain {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--db", default=argparse.SUPPRESS, help="Path to SQLite brain file")
        command_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit stable JSON")

    init = sub.add_parser("init", help="Initialize a project brain")
    add_common_options(init)
    init.add_argument("--project", default="default")
    init.add_argument("--root", default=str(Path.cwd()))
    init.add_argument("--rebind-root", action="store_true", help="Explicitly replace an existing canonical project root")

    remember_cmd = sub.add_parser("remember", help="Store a durable memory")
    add_common_options(remember_cmd)
    remember_cmd.add_argument("text")
    remember_cmd.add_argument("--project", default="default")
    remember_cmd.add_argument("--type", default="fact")
    remember_cmd.add_argument("--pramana", default="smriti", choices=["pratyaksha", "sabda", "anumana", "smriti", "kalpana"])
    remember_cmd.add_argument("--confidence", type=float, default=0.75)
    remember_cmd.add_argument("--priority", type=int, default=5)
    remember_cmd.add_argument("--source-path")
    remember_cmd.add_argument("--source-hash")
    remember_cmd.add_argument("--verification-command")
    remember_cmd.add_argument("--verification-status", choices=("unverified", "verified", "failed", "stale"), default="unverified")
    remember_cmd.add_argument("--verification-timestamp")

    ingest = sub.add_parser("ingest-repo", help="Index a repository or folder")
    add_common_options(ingest)
    ingest.add_argument("path")
    ingest.add_argument("--project", default="default")
    ingest.add_argument("--force", action="store_true", help="Re-read and re-index every eligible file even when metadata is unchanged")
    ingest.add_argument("--rebind-root", action="store_true", help="Explicitly replace the brain's canonical project root")

    watch = sub.add_parser("watch-repo", help="Continuously refresh a repository using the incremental index")
    add_common_options(watch)
    watch.add_argument("path")
    watch.add_argument("--project", default="default")
    watch.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")

    settings = sub.add_parser("settings", help="Read or update a project's indexing and retrieval policy")
    add_common_options(settings)
    settings.add_argument("--project", default="default")
    settings.add_argument("--max-file-mb", type=float)
    settings.add_argument("--parser-adapter", choices=("auto", "regex", "tree-sitter", "lsp"))
    settings.add_argument("--lsp-command")
    settings.add_argument("--embedding-provider", choices=("none", "hash", "sentence-transformers"))
    settings.add_argument("--embedding-model")
    settings.add_argument("--hybrid-weight", type=float)

    thread = sub.add_parser("ingest-thread", help="Index a long thread, transcript, JSONL session, or handoff file")
    add_common_options(thread)
    thread.add_argument("path")
    thread.add_argument("--project", default="default")
    thread.add_argument("--title")

    search_cmd = sub.add_parser("search", help="Search memories and indexed files")
    add_common_options(search_cmd)
    search_cmd.add_argument("query")
    search_cmd.add_argument("--project")
    search_cmd.add_argument("--limit", type=int, default=8)

    graph_cmd = sub.add_parser("graph", help="Read the local entity graph")
    add_common_options(graph_cmd)
    graph_cmd.add_argument("--project", default="default")
    graph_cmd.add_argument("--limit", type=int, default=100)

    pack = sub.add_parser("context-pack", help="Build a compact task context pack")
    add_common_options(pack)
    pack.add_argument("task")
    pack.add_argument("--project", default="default")
    pack.add_argument("--limit", type=int, default=8)
    pack.add_argument("--max-tokens", type=int, default=4000)

    stale = sub.add_parser("stale-check", help="Check whether indexed files changed")
    add_common_options(stale)
    stale.add_argument("--project", default="default")
    stale.add_argument("--deep", action="store_true", help="Hash file contents instead of using the fast stat manifest")
    stale.add_argument("--details", action="store_true", help="Include fresh file rows as well as anomalies")
    stale.add_argument("--detail-limit", type=int, default=50, help="Maximum freshness detail rows to emit (0-500)")

    checkpoint = sub.add_parser("checkpoint", help="Save a structured project continuation checkpoint")
    add_common_options(checkpoint)
    checkpoint.add_argument("--project", default="default")
    checkpoint.add_argument("--objective", required=True)
    checkpoint.add_argument("--verified-evidence", default="")
    checkpoint.add_argument("--remaining-gaps", default="")
    checkpoint.add_argument("--next-action", default="")
    checkpoint.add_argument("--prohibited-repetition", default="")
    checkpoint.add_argument("--expected-version", type=int)

    continuation = sub.add_parser("continue-prompt", help="Build a compact prompt for a new agent task")
    add_common_options(continuation)
    continuation.add_argument("--project", default="default")

    reflect_cmd = sub.add_parser("reflect", help="Consolidate duplicate memories and flag contradictions")
    add_common_options(reflect_cmd)
    reflect_cmd.add_argument("--project", default="default")

    mcp_config = sub.add_parser("mcp-config", help="Generate an MCP host config snippet")
    add_common_options(mcp_config)
    mcp_config.add_argument("--project", default="default")
    mcp_config.add_argument("--name", default="rta-smriti")

    bootstrap = sub.add_parser("bootstrap-project", help="Create a per-project brain, index the repo, and optionally write project agent instructions")
    add_common_options(bootstrap)
    bootstrap.add_argument("path")
    bootstrap.add_argument("--project", required=True)
    bootstrap.add_argument("--brain-dir", default=str(Path.home() / "Documents" / "Codex" / "brains"))
    bootstrap.add_argument("--write-agents", action="store_true")
    bootstrap.add_argument("--embedding-provider", choices=("none", "hash", "sentence-transformers"), default="hash")

    self_check_cmd = sub.add_parser("self-check", help="Verify that a project brain is ready to use")
    add_common_options(self_check_cmd)
    self_check_cmd.add_argument("--project", default="default")
    self_check_cmd.add_argument("--check-files", action="store_true", help="Hash indexed files to include fresh/changed/missing counts")

    projects = sub.add_parser("projects-list", help="List projects registered in a brain database")
    add_common_options(projects)

    install = sub.add_parser("install-local", help="Install local command wrappers into a target folder")
    add_common_options(install)
    install.add_argument("--target", default=str(Path.home() / ".local" / "bin"))

    doctor_cmd = sub.add_parser("doctor", help="Verify local brain health")
    add_common_options(doctor_cmd)

    publish = sub.add_parser("publish-readiness", help="Check whether this package is ready to publish on GitHub")
    add_common_options(publish)

    dashboard = sub.add_parser("dashboard", help="Run the local operator console", description="Run the local operator console")
    dashboard.add_argument("--brain-dir", default=str(Path.home() / "Documents" / "Codex" / "brains"))
    dashboard.add_argument("--db", default=None, help="Default brain DB for the opened console")
    dashboard.add_argument("--project", default=None, help="Default project for the opened console")
    dashboard.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1", help="Loopback host only")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    return parser


def build_mcp_config(db_path: str, project: str, name: str) -> dict:
    return mcp_config_payload(db_path, project, name, tool_root())


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "dashboard":
        run_dashboard(
            tool_root(),
            Path(args.brain_dir),
            default_db=Path(args.db) if args.db else None,
            default_project=args.project,
            host=args.host,
            port=args.port,
            open_browser=not args.no_open,
        )
        return 0
    if args.command == "publish-readiness":
        emit(publish_readiness(tool_root()), args.json)
        return 0
    try:
        conn = connect(Path(args.db))
        with conn:
            if args.command == "init":
                payload = init_project(conn, args.project, str(Path(args.root).resolve()), allow_root_rebind=args.rebind_root)
            elif args.command == "remember":
                provenance = None
                if any((args.source_path, args.source_hash, args.verification_command, args.verification_timestamp)) or args.verification_status != "unverified":
                    provenance = {
                        "source_path": args.source_path,
                        "source_hash": args.source_hash,
                        "command": args.verification_command,
                        "timestamp": args.verification_timestamp,
                        "verification_status": args.verification_status,
                    }
                payload = remember(
                    conn,
                    args.text,
                    project=args.project,
                    memory_type=args.type,
                    pramana=args.pramana,
                    confidence=args.confidence,
                    priority=args.priority,
                    provenance=provenance,
                )
            elif args.command == "ingest-repo":
                payload = ingest_repo(conn, Path(args.path), project=args.project, force=args.force, allow_root_rebind=args.rebind_root)
            elif args.command == "watch-repo":
                payload = watch_repository(conn, Path(args.path), project=args.project, interval_seconds=args.interval)
            elif args.command == "settings":
                changes = {}
                if args.max_file_mb is not None:
                    changes["max_file_bytes"] = round(args.max_file_mb * 1_000_000)
                for argument, key in (
                    (args.parser_adapter, "parser_adapter"),
                    (args.lsp_command, "lsp_command"),
                    (args.embedding_provider, "embedding_provider"),
                    (args.embedding_model, "embedding_model"),
                    (args.hybrid_weight, "hybrid_weight"),
                ):
                    if argument is not None:
                        changes[key] = argument
                payload = update_project_settings(conn, args.project, changes) if changes else get_project_settings(conn, args.project)
            elif args.command == "ingest-thread":
                payload = ingest_thread(conn, Path(args.path), project=args.project, title=args.title)
            elif args.command == "search":
                payload = search(conn, args.query, project=args.project, limit=args.limit)
            elif args.command == "graph":
                payload = graph(conn, project=args.project, limit=args.limit)
            elif args.command == "context-pack":
                payload = build_context_pack(
                    conn, args.task, project=args.project, limit=args.limit, max_tokens=args.max_tokens
                )
            elif args.command == "stale-check":
                payload = stale_check(
                    conn,
                    project=args.project,
                    deep=args.deep,
                    detail_limit=args.detail_limit,
                    include_fresh_details=args.details,
                )
            elif args.command == "checkpoint":
                payload = save_checkpoint(
                    conn,
                    project=args.project,
                    objective=args.objective,
                    verified_evidence=args.verified_evidence,
                    remaining_gaps=args.remaining_gaps,
                    next_action=args.next_action,
                    prohibited_repetition=args.prohibited_repetition,
                    expected_version=args.expected_version,
                )
            elif args.command == "continue-prompt":
                payload = build_continuation_prompt(conn, project=args.project)
            elif args.command == "reflect":
                payload = reflect(conn, project=args.project)
            elif args.command == "mcp-config":
                payload = build_mcp_config(args.db, args.project, args.name)
            elif args.command == "bootstrap-project":
                payload = bootstrap_project(
                    conn,
                    Path(args.path),
                    args.project,
                    Path(args.brain_dir),
                    args.write_agents,
                    tool_root(),
                    embedding_provider=args.embedding_provider,
                )
            elif args.command == "self-check":
                payload = self_check(conn, project=args.project, check_files=args.check_files)
            elif args.command == "projects-list":
                payload = projects_list(conn)
            elif args.command == "install-local":
                payload = install_local(Path(args.target), tool_root())
            elif args.command == "doctor":
                payload = doctor(conn)
            else:
                parser.error(f"unknown command: {args.command}")
                return 2
        emit(payload, args.json)
        return 0
    except Exception as exc:
        error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
        if getattr(args, "json", False):
            print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
